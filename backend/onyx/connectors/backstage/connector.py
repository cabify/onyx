"""Backstage connector for Onyx.

This connector extends the BlobStorageConnector to specifically handle Backstage
documentation pages stored in S3 buckets, to reuse most of the logic from the BlobStorageConnector.
For performance we override the _yield_blob_objects instead of post-processing the original _yield_blob_objects result.

The connector is hardcoded to use the S3 bucket. From that bucket we only handle the 'index.html' files.
Also we use the path of the file to generate the backstage URL.
"""

import os
from datetime import datetime
from datetime import timezone
from typing import Any, List

import boto3
from botocore.client import Config
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import BlobType, DocumentSource
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.models import ConnectorMissingCredentialError, Document, TextSection
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.file_processing.html_utils import web_html_cleanup, parse_html_page_basic
from onyx.utils.logger import setup_logger

logger = setup_logger()


class BackstageConnector(BlobStorageConnector):
    """Connector for Backstage documentation pages stored in S3.
    
    This connector extends the BlobStorageConnector to specifically:
    1. Only handle files named 'index.html'
    2. Transform S3 links to Backstage URLs
    3. Extract text content from HTML files
    """
    
    def __init__(
        self,
        bucket_type: str = BlobType.S3.value,
        bucket_name: str = "",
        backstage_url: str = "",
        prefix: str = "",
        batch_size: int = INDEX_BATCH_SIZE
    ) -> None:
        # Force S3 as the only supported bucket type, but accept bucket_type for compatibility
        super().__init__(
            bucket_type=BlobType.S3.value,
            bucket_name=bucket_name,
            prefix=prefix,
            batch_size=batch_size
        )
        self._allow_images = False  # Always disable images for backstage connector
        self.backstage_url = backstage_url[:-1] if backstage_url.endswith("/") else backstage_url
        self.minio_endpoint_url = os.environ.get("MINIO_ENDPOINT_URL", "")

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Override to handle MinIO connections if endpoint URL is provided."""

        if not all(
            credentials.get(key)
            for key in ["aws_access_key_id", "aws_secret_access_key"]
        ):
            raise ConnectorMissingCredentialError("Custom MinIO")


        if self.minio_endpoint_url:
            session = boto3.session.Session()
            self.s3_client = session.client(
                "s3",
                endpoint_url=self.minio_endpoint_url,
                aws_access_key_id=credentials.get("aws_access_key_id"),
                aws_secret_access_key=credentials.get("aws_secret_access_key"),
                region_name="us-east-1",
                config=Config(signature_version="s3v4"),
            )
            return None

        else:
            # Fall back to parent S3 logic
            return super().load_credentials(credentials)

    # Override the _yield_blob_objects parent method to specifically handle Backstage documentation pages
    def _yield_blob_objects(
        self,
        start: datetime,
        end: datetime,
    ) -> GenerateDocumentsOutput:
        if self.s3_client is None:
            raise Exception("S3 client not initialized")

        paginator = self.s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.prefix)

        batch: List[Document] = []
        for page in pages:
            if "Contents" not in page:
                continue

            for obj in page["Contents"]:
                key = obj["Key"]
                
                # Skip directories and non-index.html files
                if key.endswith("/") or not key.endswith("index.html"):
                    continue

                last_modified = obj["LastModified"].replace(tzinfo=timezone.utc)

                if not start <= last_modified <= end:
                    continue

                try:
                    downloaded_file = self._download_object(key)
                    html_content = downloaded_file.decode('utf-8', errors='replace')
                    semantic_id = self._generate_semantic_identifier(key, html_content)
                    sections = self._split_document_into_sections(html_content, key)

                    batch.append(
                        Document(
                            id=f"backstage:{self.bucket_name}:{key}",
                            sections=sections,
                            source=DocumentSource.BACKSTAGE,
                            semantic_identifier=semantic_id,
                            doc_updated_at=last_modified,
                            metadata={
                                "original_path": key,
                                "backstage_path": key.rsplit('/', 1)[0] if '/' in key else '',
                            },
                        )
                    )
                    
                    if len(batch) == self.batch_size:
                        yield batch
                        batch = []

                except Exception as e:
                    logger.exception(f"Error processing Backstage HTML file {key}: {e}")
                    continue
                    
        if batch:
            yield batch
    
    def _generate_semantic_identifier(self, key: str, html_content: str = "") -> str:
        # Try to extract title from HTML if available
        if html_content:
            try:
                parsed_html = web_html_cleanup(html_content)
                if parsed_html.title:
                    return parsed_html.title
            except Exception as e:
                logger.debug(f"Error extracting title from HTML: {e}")
        
        # Default to using the directory path as the semantic identifier
        path = key.rsplit('/', 1)[0] if '/' in key else ''
        return path or "Backstage Root"

    def _split_document_into_sections(self, html_content: str, key: str) -> List[TextSection]:
        backstage_url = self._get_backstage_url(key)
        sanitized_content = self._sanitize_html_content(html_content)

        # Currently returns a single section with the entire content
        return [TextSection(link=backstage_url, text=sanitized_content)]
    
    def _sanitize_html_content(self, html_content: str) -> str:
        try:
            parsed_html = web_html_cleanup(html_content)
            return parsed_html.cleaned_text
        except Exception as e:
            logger.warning(f"Error sanitizing HTML: {e}. Falling back to basic parsing.")
            try:
                return parse_html_page_basic(html_content)
            except Exception as e2:
                logger.error(f"Error with basic HTML parsing: {e2}. Returning raw HTML.")
                return html_content
    
    def _get_backstage_url(self, key: str) -> str:
        # Remove the 'index.html' part from the path
        path = key.rsplit('/', 1)[0] if '/' in key else ''
        return f"{self.backstage_url}/{path}"
