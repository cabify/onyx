"""Markdown Section Splitter for Backstage connector.

This module provides functionality to split markdown documents into sections
based on headers (# ## ### etc.) with two approaches:
- Hierarchical: Each section includes its content + all subsections content (text duplication)
- Non-hierarchical: Each section includes only its own content (no duplication)
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Configuration constant - change this to switch between approaches
# True for hierarchical (with content duplication), False for non-hierarchical (no duplication)
USE_HIERARCHICAL_SPLITTING = True


class SplittingMode(Enum):
    """Enum for section splitting modes."""
    HIERARCHICAL = "hierarchical"  # Includes subsection content in parent sections
    NON_HIERARCHICAL = "non_hierarchical"  # Each section contains only its own content


@dataclass
class MarkdownSection:
    """Represents a markdown section with its metadata."""
    title: str
    content: str
    level: int  # Header level (1 for #, 2 for ##, etc.)
    anchor_id: str  # The id from the HTML header (for URL fragments)
    start_line: Optional[int] = None
    end_line: Optional[int] = None


@dataclass 
class HeaderInfo:
    """Information about a markdown header."""
    title: str
    level: int
    anchor_id: str
    line_number: int


class MarkdownSectionSplitter:
    """Class to split markdown content into sections based on headers."""

    def __init__(self, splitting_mode: Optional[SplittingMode] = None):
        """Initialize the splitter with the specified mode.
        
        Args:
            splitting_mode: The splitting mode to use. If None, uses the global constant.
        """
        if splitting_mode is None:
            self.splitting_mode = (
                SplittingMode.HIERARCHICAL if USE_HIERARCHICAL_SPLITTING 
                else SplittingMode.NON_HIERARCHICAL
            )
        else:
            self.splitting_mode = splitting_mode

        print(f"Splitting mode: {self.splitting_mode}")

    def extract_section_anchors_from_html(self, html_content: str) -> dict[str, str]:
        """Extract section anchors from HTML headers.
        
        This method finds all headers with id attributes and headerlink anchors,
        mapping the header text to its anchor ID.
        
        Args:
            html_content: The HTML content to parse
            
        Returns:
            Dict mapping header text (cleaned) to anchor ID
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        section_anchors = {}
        
        # Find all headers (h1, h2, h3, h4, h5, h6) that have both id and headerlink
        for level in range(1, 7):
            headers = soup.find_all(f'h{level}', id=True)
            for header in headers:
                anchor_id = header.get('id', '')
                if not anchor_id:
                    continue
                
                # Extract the text content, excluding the headerlink anchor
                headerlink = header.find('a', class_='headerlink')
                if headerlink:
                    headerlink.decompose()  # Remove the headerlink from the text
                
                header_text = header.get_text().strip()
                if header_text and anchor_id:
                    section_anchors[header_text] = anchor_id
                    
        return section_anchors

    def parse_markdown_headers(self, markdown_content: str, section_anchors: dict[str, str]) -> List[HeaderInfo]:
        """Parse markdown content to extract header information.
        
        Args:
            markdown_content: The markdown content to parse
            section_anchors: Mapping from header text to anchor IDs
            
        Returns:
            List of HeaderInfo objects sorted by line number
        """
        lines = markdown_content.split('\n')
        headers = []
        in_code_block = False
        code_block_marker = None  # Track the specific marker used (```, ~~~, etc.)
        
        for line_num, line in enumerate(lines, 1):
            stripped_line = line.strip()
            
            # Check for code block markers (``` or ~~~)
            if stripped_line.startswith('```') or stripped_line.startswith('~~~'):
                if not in_code_block:
                    # Starting a code block
                    in_code_block = True
                    code_block_marker = stripped_line[:3]  # Store the marker type
                elif stripped_line.startswith(code_block_marker):
                    # Ending a code block (must match the opening marker)
                    in_code_block = False
                    code_block_marker = None
                continue
            
            # Skip processing headers if we're inside a code block
            if in_code_block:
                continue
            
            # Check for indented code blocks (4+ spaces or 1+ tabs)
            if line.startswith('    ') or line.startswith('\t'):
                continue
            
            # Match markdown headers (# ## ### etc.) - only when not in code blocks
            header_match = re.match(r'^(#{1,6})\s+(.+)$', stripped_line)
            if header_match:
                level = len(header_match.group(1))  # Count the # symbols
                title = header_match.group(2).strip()
                
                # Find the corresponding anchor ID
                anchor_id = section_anchors.get(title, '')
                if not anchor_id:
                    # Try to find a close match (in case of minor text differences)
                    anchor_id = self._find_closest_anchor_match(title, section_anchors)
                
                headers.append(HeaderInfo(
                    title=title,
                    level=level,
                    anchor_id=anchor_id,
                    line_number=line_num
                ))
        
        return headers

    def _find_closest_anchor_match(self, title: str, section_anchors: dict[str, str]) -> str:
        """Find the closest matching anchor for a title.
        
        This handles cases where the HTML title might differ slightly from the markdown title.
        """
        title_lower = title.lower()
        
        # First try exact match (case insensitive)
        for anchor_title, anchor_id in section_anchors.items():
            if anchor_title.lower() == title_lower:
                return anchor_id
        
        # Then try partial matches
        for anchor_title, anchor_id in section_anchors.items():
            if title_lower in anchor_title.lower() or anchor_title.lower() in title_lower:
                return anchor_id
        
        # If no match found, generate anchor from title
        return self._generate_anchor_from_title(title)

    def _generate_anchor_from_title(self, title: str) -> str:
        """Generate an anchor ID from a title using common conventions.
        
        This follows typical markdown-to-HTML anchor generation rules.
        """
        # Convert to lowercase, replace spaces and special chars with hyphens
        anchor = re.sub(r'[^\w\s-]', '', title.lower())
        anchor = re.sub(r'[-\s]+', '-', anchor)
        return anchor.strip('-')

    def split_into_sections(
        self, 
        markdown_content: str, 
        html_content: str = ""
    ) -> List[MarkdownSection]:
        """Split markdown content into sections.
        
        Args:
            markdown_content: The markdown content to split
            html_content: Optional HTML content to extract anchor information
            
        Returns:
            List of MarkdownSection objects
        """
        # Extract anchor mappings from HTML if provided
        section_anchors = {}
        if html_content:
            section_anchors = self.extract_section_anchors_from_html(html_content)
        
        # Parse headers
        headers = self.parse_markdown_headers(markdown_content, section_anchors)
        
        if not headers:
            # No headers found, return the entire content as one section
            return [MarkdownSection(
                title="Document",
                content=markdown_content,
                level=1,
                anchor_id="document",
                start_line=1,
                end_line=len(markdown_content.split('\n'))
            )]
        
        # Split content based on the chosen mode
        if self.splitting_mode == SplittingMode.HIERARCHICAL:
            return self._split_hierarchical(markdown_content, headers)
        else:
            return self._split_non_hierarchical(markdown_content, headers)

    def _split_non_hierarchical(
        self, 
        markdown_content: str, 
        headers: List[HeaderInfo]
    ) -> List[MarkdownSection]:
        """Split content with each section containing only its own content (no duplication).
        
        Args:
            markdown_content: The markdown content
            headers: List of header information
            
        Returns:
            List of MarkdownSection objects
        """
        lines = markdown_content.split('\n')
        sections = []
        
        for i, header in enumerate(headers):
            start_line = header.line_number
            
            # Find the end line (start of next header of ANY level for non-hierarchical)
            end_line = len(lines)
            if i + 1 < len(headers):
                # In non-hierarchical mode, each section ends at the next header regardless of level
                end_line = headers[i + 1].line_number - 1
            
            # Extract section content
            section_lines = lines[start_line - 1:end_line]  # -1 because line_number is 1-based
            content = '\n'.join(section_lines).strip()
            
            sections.append(MarkdownSection(
                title=header.title,
                content=content,
                level=header.level,
                anchor_id=header.anchor_id,
                start_line=start_line,
                end_line=end_line
            ))
        
        return sections

    def _split_hierarchical(
        self, 
        markdown_content: str, 
        headers: List[HeaderInfo]
    ) -> List[MarkdownSection]:
        """Split content with each section including its subsections (with duplication).
        
        Args:
            markdown_content: The markdown content
            headers: List of header information
            
        Returns:
            List of MarkdownSection objects
        """
        lines = markdown_content.split('\n')
        sections = []
        
        for i, header in enumerate(headers):
            start_line = header.line_number
            
            # Find the end line (start of next header at same or higher level)
            end_line = len(lines)
            for j in range(i + 1, len(headers)):
                if headers[j].level <= header.level:
                    end_line = headers[j].line_number - 1
                    break
            
            # Extract section content including all subsections
            section_lines = lines[start_line - 1:end_line]  # -1 because line_number is 1-based
            content = '\n'.join(section_lines).strip()
            
            sections.append(MarkdownSection(
                title=header.title,
                content=content,
                level=header.level,
                anchor_id=header.anchor_id,
                start_line=start_line,
                end_line=end_line
            ))
        
        return sections

    def create_section_url(self, base_url: str, anchor_id: str) -> str:
        """Create a full URL for a section including the anchor.
        
        Args:
            base_url: The base URL of the document
            anchor_id: The anchor ID for the section
            
        Returns:
            Full URL with anchor fragment
        """
        if not anchor_id:
            return base_url
        return f"{base_url}/#{anchor_id}" 