"""Backstage connector for Onyx.

This connector extends the BlobStorageConnector to specifically handle Backstage
documentation pages stored in S3 buckets, to reuse most of the logic from the BlobStorageConnector.
For performance we override the _yield_blob_objects instead of post-processing the original _yield_blob_objects result.

The connector is hardcoded to use the S3 bucket. From that bucket we only handle the 'index.html' files.
Also we use the path of the file to generate the backstage URL.
"""

from datetime import datetime
from datetime import timezone
from typing import List

from onyx.configs.constants import BlobType, DocumentSource
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.models import Document, TextSection
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
        prefix: str = "",
        batch_size: int = 10,
        sanitize_html: bool = False,
    ) -> None:
        """Initialize the Backstage connector.
        
        Args:
            bucket_type: (ignored, for compatibility with config)
            bucket_name: Name of the S3 bucket
            prefix: Prefix to filter objects in the bucket
            batch_size: Number of documents to process in a batch
            sanitize_html: Whether to sanitize HTML content (extract text only)
        """
        # Force S3 as the only supported bucket type, but accept bucket_type for compatibility
        super().__init__(
            bucket_type=bucket_type,
            bucket_name=bucket_name,
            prefix=prefix,
            batch_size=batch_size
        )
        self._allow_images = False  # Always disable images for backstage connector
        self._sanitize_html = sanitize_html
    
    def _get_backstage_url(self, key: str) -> str:
        """Convert S3 object key to Backstage URL.
        
        Args:
            key: S3 object key
            
        Returns:
            Backstage URL for the documentation
        """
        # Remove the 'index.html' part from the path
        path = key.rsplit('/', 1)[0] if '/' in key else ''
        return f"https://backstage.cabify.tools/docs/{path}"
    
    def _sanitize_html_content(self, html_content: str) -> str:
        """Sanitize HTML content to extract text.
        
        If sanitize_html is enabled, this method will extract clean text from HTML.
        Otherwise, it returns the raw HTML.
        
        Args:
            html_content: Raw HTML content
            
        Returns:
            Text content or raw HTML depending on sanitize_html setting
        """
            
        try:
            # Use the web_html_cleanup utility to extract clean text
            parsed_html = web_html_cleanup(html_content)
            return parsed_html.cleaned_text
        except Exception as e:
            logger.warning(f"Error sanitizing HTML: {e}. Falling back to basic parsing.")
            try:
                # Fallback to basic HTML parsing
                return parse_html_page_basic(html_content)
            except Exception as e2:
                logger.error(f"Error with basic HTML parsing: {e2}. Returning raw HTML.")
                return html_content
    
    def _generate_semantic_identifier(self, key: str, html_content: str = "") -> str:
        """Generate a semantic identifier for the document.
        
        Args:
            key: S3 object key
            html_content: HTML content to extract title from (if available)
            
        Returns:
            A semantic identifier for the document
        """
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
    
    def _yield_blob_objects(
        self,
        start: datetime,
        end: datetime,
    ) -> GenerateDocumentsOutput:
        """Yield document objects from the S3 bucket.
        
        This method overrides the parent method to specifically filter for
        'index.html' files and transform them into Backstage documents.
        
        Args:
            start: Start datetime for filtering objects
            end: End datetime for filtering objects
            
        Yields:
            Batches of Document objects
        """
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

                logger.info(f"Processing key: {key}")

                try:
                    # Download and process the HTML file
                    downloaded_file = self._download_object(key)
                    
                    # Get the raw HTML content
                    html_content = downloaded_file.decode('utf-8', errors='replace')
                    
                    # Generate a semantic identifier (potentially using the HTML title)
                    semantic_id = self._generate_semantic_identifier(key, html_content)
                    
                    # Generate the backstage URL
                    backstage_url = self._get_backstage_url(key)
                    
                    # Prepare sections (potentially splitting the document)
                    sections = self._split_document_into_sections(html_content, key)
                    
                    # Create a document
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
                    # Log the error and continue
                    logger.exception(f"Error processing Backstage HTML file {key}: {e}")
                    continue
                    
        if batch:
            yield batch

    def _split_document_into_sections(self, html_content: str, key: str) -> List[TextSection]:
        """Split an HTML document into multiple sections.
        
        Currently returns a single section with the entire content.
        In the future, this could be extended to split HTML content into logical sections.
        
        Args:
            html_content: Raw HTML content
            key: S3 object key
            
        Returns:
            List of TextSection objects
        """
        backstage_url = self._get_backstage_url(key)
        sanitized_content = self._sanitize_html_content(html_content)

        # Currently returns a single section with the entire content
        return [TextSection(link=backstage_url, text=sanitized_content)]
    
    def set_sanitize_html(self, value: bool) -> None:
        """Set whether to sanitize HTML content.
        
        Args:
            value: True to sanitize HTML (extract text only), False to use raw HTML
        """
        self._sanitize_html = value
        logger.info(f"HTML sanitization set to: {value}") 