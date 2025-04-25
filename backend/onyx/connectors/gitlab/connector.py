import fnmatch
import itertools
from collections import deque
from collections.abc import Iterable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

import gitlab
import pytz
from gitlab.v4.objects import Project

from onyx.configs.app_configs import GITLAB_CONNECTOR_INCLUDE_CODE_FILES
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger


logger = setup_logger()

# List of directories/Files to exclude
exclude_patterns = [
    "logs",
    ".github/",
    ".gitlab/",
    ".pre-commit-config.yaml",
]


def _batch_gitlab_objects(
    git_objs: Iterable[Any], batch_size: int
) -> Iterator[list[Any]]:
    it = iter(git_objs)
    while True:
        batch = list(itertools.islice(it, batch_size))
        if not batch:
            break
        yield batch


def get_author(author: Any) -> BasicExpertInfo:
    return BasicExpertInfo(
        display_name=author.get("name"),
    )


def _convert_merge_request_to_document(mr: Any) -> Document:
    doc = Document(
        id=mr.web_url,
        sections=[TextSection(link=mr.web_url, text=mr.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=mr.title,
        # updated_at is UTC time but is timezone unaware, explicitly add UTC
        # as there is logic in indexing to prevent wrong timestamped docs
        # due to local time discrepancies with UTC
        doc_updated_at=mr.updated_at.replace(tzinfo=timezone.utc),
        primary_owners=[get_author(mr.author)],
        metadata={"state": mr.state, "type": "MergeRequest"},
    )
    return doc


def _convert_issue_to_document(issue: Any) -> Document:
    doc = Document(
        id=issue.web_url,
        sections=[TextSection(link=issue.web_url, text=issue.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=issue.title,
        # updated_at is UTC time but is timezone unaware, explicitly add UTC
        # as there is logic in indexing to prevent wrong timestamped docs
        # due to local time discrepancies with UTC
        doc_updated_at=issue.updated_at.replace(tzinfo=timezone.utc),
        primary_owners=[get_author(issue.author)],
        metadata={"state": issue.state, "type": issue.type if issue.type else "Issue"},
    )
    return doc


def _convert_code_to_document(
    project: Project, file: Any, url: str, projectName: str, projectOwner: str
) -> Document:
    # Dynamically get the default branch from the project object
    default_branch = project.default_branch

    # Fetch the file content using the correct branch
    file_content_obj = project.files.get(
        file_path=file["path"], ref=default_branch  # Use the default branch
    )
    try:
        file_content = file_content_obj.decode().decode("utf-8")
    except UnicodeDecodeError:
        file_content = file_content_obj.decode().decode("latin-1")

    # Construct the file URL dynamically using the default branch
    file_url = (
        f"{url}/{projectOwner}/{projectName}/-/blob/{default_branch}/{file['path']}"
    )

    # Create and return a Document object
    doc = Document(
        id=file["id"],
        sections=[TextSection(link=file_url, text=file_content)],
        source=DocumentSource.GITLAB,
        semantic_identifier=file["name"],
        doc_updated_at=datetime.now().replace(tzinfo=timezone.utc),
        primary_owners=[],  # Add owners if needed
        metadata={"type": "CodeFile"},
    )
    return doc


def _should_exclude(path: str) -> bool:
    """Check if a path matches any of the exclude patterns."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude_patterns)


class GitlabConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        project_owner: str,
        project_name: str,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",
        include_mrs: bool = True,
        include_issues: bool = True,
        include_code_files: bool = GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
    ) -> None:
        self.project_owner = project_owner
        self.project_name = project_name
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_mrs = include_mrs
        self.include_issues = include_issues
        self.include_code_files = include_code_files
        self.gitlab_client: gitlab.Gitlab | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.gitlab_client = gitlab.Gitlab(
            credentials["gitlab_url"], private_token=credentials["gitlab_access_token"]
        )
        return None

    def _fetch_from_gitlab(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")
        project: gitlab.Project = self.gitlab_client.projects.get(
            f"{self.project_owner}/{self.project_name}"
        )

        # Fetch code files
        if self.include_code_files:
            # Fetching using BFS as project.report_tree with recursion causing slow load
            queue = deque([""])  # Start with the root directory
            while queue:
                current_path = queue.popleft()
                files = project.repository_tree(path=current_path, all=True)
                for file_batch in _batch_gitlab_objects(files, self.batch_size):
                    code_doc_batch: list[Document] = []
                    for file in file_batch:
                        if _should_exclude(file["path"]):
                            continue

                        if file["type"] == "blob":
                            code_doc_batch.append(
                                _convert_code_to_document(
                                    project,
                                    file,
                                    self.gitlab_client.url,
                                    self.project_name,
                                    self.project_owner,
                                )
                            )
                        elif file["type"] == "tree":
                            queue.append(file["path"])

                    if code_doc_batch:
                        yield code_doc_batch

        if self.include_mrs:
            merge_requests = project.mergerequests.list(
                state=self.state_filter, order_by="updated_at", sort="desc"
            )

            for mr_batch in _batch_gitlab_objects(merge_requests, self.batch_size):
                mr_doc_batch: list[Document] = []
                for mr in mr_batch:
                    mr.updated_at = datetime.strptime(
                        mr.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if start is not None and mr.updated_at < start.replace(
                        tzinfo=pytz.UTC
                    ):
                        yield mr_doc_batch
                        return
                    if end is not None and mr.updated_at > end.replace(tzinfo=pytz.UTC):
                        continue
                    mr_doc_batch.append(_convert_merge_request_to_document(mr))
                yield mr_doc_batch

        if self.include_issues:
            issues = project.issues.list(state=self.state_filter)

            for issue_batch in _batch_gitlab_objects(issues, self.batch_size):
                issue_doc_batch: list[Document] = []
                for issue in issue_batch:
                    issue.updated_at = datetime.strptime(
                        issue.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if start is not None:
                        start = start.replace(tzinfo=pytz.UTC)
                        if issue.updated_at < start:
                            yield issue_doc_batch
                            return
                    if end is not None:
                        end = end.replace(tzinfo=pytz.UTC)
                        if issue.updated_at > end:
                            continue
                    issue_doc_batch.append(_convert_issue_to_document(issue))
                yield issue_doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_gitlab()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._fetch_from_gitlab(start_datetime, end_datetime)


class GitlabMarkdownOnlyConnector(GitlabConnector):
    """GitLab connector that only processes markdown files."""
    
    _exclude_patterns = [
        "logs",
        ".github/",
        ".gitlab/",
        ".pre-commit-config.yaml",
    ]

    _markdown_extensions = [
        ".md",
        ".markdown", 
        ".mdx",
        ".mdown",
        ".mkd",
        ".mkdn",
        "README*"
    ]

    def __init__(
        self,
        project_owner: str,
        project_name: str,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",  # Ignored but kept for compatibility
        include_mrs: bool = True,   # Ignored but kept for compatibility
        include_issues: bool = True, # Ignored but kept for compatibility
        include_code_files: bool = True, # Always True for this connector
        is_group: bool = False,
    ) -> None:
        project_owner = project_owner.strip().rstrip('/')
        project_name = project_name.strip().rstrip('/')
        self.is_group = is_group or '/' in project_name

        super().__init__(
            project_owner=project_owner,
            project_name=project_name,
            batch_size=batch_size,
            state_filter="all",
            include_mrs=False,
            include_issues=False,
            include_code_files=True,
        )

    def _get_group_path(self) -> str:
        """Construct the full group path."""
        # Clean and join paths, removing empty segments
        parts = []
        if self.project_owner:
            parts.extend(part for part in self.project_owner.split('/') if part)
        if self.project_name:
            parts.extend(part for part in self.project_name.split('/') if part)
        
        # Join with forward slashes
        return '/'.join(parts)

    def _get_projects(self) -> list[Project]:
        """Get all projects from either a single project or a group."""
        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")

        try:
            group_path = self._get_group_path()
            logger.info(f"Processing path: {group_path} (is_group={self.is_group})")

            if self.is_group:
                try:
                    # Try direct group access first
                    try:
                        matching_group = self.gitlab_client.groups.get(group_path)
                        logger.info(f"Found group by direct path: {matching_group.full_path} (ID: {matching_group.id})")
                    except gitlab.exceptions.GitlabGetError:
                        # If direct access fails, try search
                        logger.info(f"Direct access failed, trying search for group: {group_path}")
                        groups = self.gitlab_client.groups.list(search=group_path, all=True)
                        logger.info(f"Found {len(groups)} groups matching search: {group_path}")
                        
                        # Log all found groups for debugging
                        for g in groups:
                            logger.info(f"Found group in search: {g.full_path} (ID: {g.id})")
                        
                        # Find the exact matching group
                        matching_group = None
                        for group in groups:
                            if group.full_path.lower() == group_path.lower():
                                matching_group = group
                                logger.info(f"Exact match found: {group.full_path} (ID: {group.id})")
                                break
                        
                        if matching_group is None:
                            logger.error(f"No matching group found for path: {group_path}")
                            return []
                    
                    # Get all projects including subgroups
                    group_projects = matching_group.projects.list(include_subgroups=True, all=True)
                    logger.info(f"Found {len(group_projects)} projects in group {matching_group.full_path}")
                    
                    # Convert GroupProject objects to full Project objects
                    projects = []
                    for group_project in group_projects:
                        try:
                            # Get the full project object using the ID
                            project = self.gitlab_client.projects.get(group_project.id)
                            logger.info(f"Loaded full project: {project.path_with_namespace}")
                            projects.append(project)
                        except gitlab.exceptions.GitlabGetError as e:
                            logger.error(f"Failed to load full project {group_project.path_with_namespace}: {str(e)}")
                            continue
                    
                    return projects
                    
                except gitlab.exceptions.GitlabGetError as e:
                    if e.response_code == 404:
                        logger.error(f"Group not found: {group_path}")
                    else:
                        logger.error(f"Error accessing group {group_path}: {str(e)}")
                    return []
                except Exception as e:
                    logger.error(f"Unexpected error accessing group {group_path}: {str(e)}")
                    return []
            else:
                logger.info(f"Fetching single project: {group_path}")
                try:
                    # Try direct project access first
                    try:
                        project = self.gitlab_client.projects.get(group_path)
                        logger.info(f"Found project by direct path: {project.path_with_namespace}")
                        return [project]
                    except gitlab.exceptions.GitlabGetError:
                        # If direct access fails, try search
                        projects = self.gitlab_client.projects.list(search=group_path)
                        logger.info(f"Found {len(projects)} projects matching search: {group_path}")
                        
                        for project in projects:
                            if project.path_with_namespace.lower() == group_path.lower():
                                # Get the full project object
                                full_project = self.gitlab_client.projects.get(project.id)
                                logger.info(f"Found matching project: {full_project.path_with_namespace}")
                                return [full_project]
                        
                        logger.error(f"No matching project found for path: {group_path}")
                        return []
                        
                except gitlab.exceptions.GitlabGetError as e:
                    if e.response_code == 404:
                        logger.error(f"Project not found: {group_path}")
                    else:
                        logger.error(f"Error accessing project {group_path}: {str(e)}")
                    return []
                except Exception as e:
                    logger.error(f"Unexpected error accessing project {group_path}: {str(e)}")
                    return []
        except gitlab.exceptions.GitlabError as e:
            logger.error(f"Error fetching projects: {str(e)}")
            return []

    def _should_exclude(self, path: str) -> bool:
        """Check if a path matches any of the exclude patterns."""
        return any(fnmatch.fnmatch(path, pattern) for pattern in self._exclude_patterns)

    def _is_markdown_file(self, path: str) -> bool:
        """Check if a file is a markdown file."""
        filename = path.lower()
        basename = path.split('/')[-1].lower()
        
        # Check if it's a README file (case insensitive)
        if basename.startswith('readme'):
            return True
            
        # Check file extensions
        return any(filename.endswith(ext.lower()) for ext in self._markdown_extensions)

    def _convert_code_to_document(
        self, project: Project, file: Any, url: str, projectName: str, projectOwner: str
    ) -> Document | None:
        try:
            file_content_obj = project.files.get(
                file_path=file["path"], ref=project.default_branch or "master"
            )
            try:
                file_content = file_content_obj.decode().decode("utf-8")
            except UnicodeDecodeError:
                file_content = file_content_obj.decode().decode("latin-1")

            file_url = f"{url}/{project.path_with_namespace}/-/blob/{project.default_branch or 'master'}/{file['path']}"
            
            semantic_name = file["path"].split('/')[-1]
            if semantic_name.lower().startswith('readme'):
                semantic_name = f"README - {project.name}"
                
            doc_id = f"gitlab:{project.path_with_namespace}:{file['path']}"
                
            doc = Document(
                id=doc_id,
                sections=[{"text": file_content, "link": file_url}],
                source=DocumentSource.GITLAB,
                semantic_identifier=semantic_name,
                doc_updated_at=datetime.now().replace(tzinfo=timezone.utc),
                primary_owners=[],
                metadata={
                    "type": "MarkdownFile",
                    "repository": project.name,
                    "path": file["path"],
                    "project": project.path_with_namespace,
                    "file_url": file_url,
                    "file_id": file["id"]
                },
            )
            logger.info(f"Converted file {file['path']} to document")
            return doc
        except Exception as e:
            logger.error(f"Error converting file {file['path']} to document: {str(e)}")
            return None

    def _fetch_from_gitlab(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")

        projects = self._get_projects()
        
        for project in projects:
            logger.info(f"Processing project: {project.path_with_namespace}")
            
            # Solo procesar archivos markdown
            queue = deque([""])  # Empezar con el directorio raíz
            while queue:
                current_path = queue.popleft()
                try:
                    files = project.repository_tree(path=current_path, all=True)
                    for file_batch in _batch_gitlab_objects(files, self.batch_size):
                        code_doc_batch: list[Document] = []
                        for file in file_batch:
                            if self._should_exclude(file["path"]):
                                continue

                            if file["type"] == "blob" and self._is_markdown_file(file["path"]):
                                doc = self._convert_code_to_document(
                                    project,
                                    file,
                                    self.gitlab_client.url,
                                    project.name,
                                    project.path_with_namespace,
                                )
                                if doc:
                                    code_doc_batch.append(doc)
                            elif file["type"] == "tree":
                                queue.append(file["path"])

                        if code_doc_batch:
                            yield code_doc_batch
                except Exception as e:
                    logger.error(f"Error processing path {current_path} in project {project.path_with_namespace}: {str(e)}")
                    continue


if __name__ == "__main__":
    import os

    connector = GitlabMarkdownOnlyConnector(
        project_owner=os.environ["PROJECT_OWNER"],
        project_name=os.environ["PROJECT_NAME"],
        batch_size=10,
        is_group=True,
    )

    connector.load_credentials(
        {
            "gitlab_access_token": os.environ["GITLAB_ACCESS_TOKEN"],
            "gitlab_url": os.environ["GITLAB_URL"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
