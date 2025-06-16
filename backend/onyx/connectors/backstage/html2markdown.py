#!/usr/bin/env python3
"""
HTML to Markdown Converter for MkDocs/TechDocs generated documentation.

This script extracts content from HTML documentation pages and converts them
back to markdown format, preserving structure, code blocks, links, and lists.
"""

import re
import html
from bs4 import BeautifulSoup


class HTMLToMarkdownConverter:
    def __init__(self):
        self.output_lines = []
        
    def convert_file(self, html_file_path, output_file_path=None):
        """Convert HTML file to markdown."""
        try:
            with open(html_file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except FileNotFoundError:
            print(f"Error: File '{html_file_path}' not found.")
            return False
        except Exception as e:
            print(f"Error reading file: {e}")
            return False
            
        markdown_content = self.convert_html_to_markdown(html_content)
        
        if output_file_path:
            try:
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                print(f"Markdown content written to '{output_file_path}'")
            except Exception as e:
                print(f"Error writing file: {e}")
                return False
        else:
            print(markdown_content)
            
        return True
    
    def convert_html_to_markdown(self, html_content):
        """Convert HTML content to markdown."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the main content area (MkDocs typically uses this structure)
        main_content = soup.find('article', class_='md-content__inner md-typeset')
        
        if not main_content:
            # Fallback: try to find content in other common containers
            main_content = soup.find('div', class_='md-content')
            if not main_content:
                main_content = soup.find('main')
                if not main_content:
                    print("Warning: Could not find main content area. Processing entire body.")
                    main_content = soup.find('body')
        
        if not main_content:
            return "Error: Could not extract content from HTML."
        
        self.output_lines = []
        self.process_element(main_content)
        
        # Clean up the output
        markdown_content = '\n'.join(self.output_lines)
        markdown_content = self.clean_markdown(markdown_content)
        
        return markdown_content
    
    def process_element(self, element):
        """Process HTML elements recursively."""
        if element.name is None:  # Text node
            text = str(element).strip()
            if text:
                self.output_lines.append(text)
            return
        
        # Skip navigation, sidebars, and other non-content elements
        if element.get('class'):
            classes = ' '.join(element.get('class', []))
            if any(skip_class in classes for skip_class in [
                'md-nav', 'md-sidebar', 'md-header', 'md-footer', 
                'md-search', 'headerlink', 'md-content__button',
                'linenos', 'linenodiv', 'md-source-file'  # Skip metadata sections
            ]):
                return
        
        # Skip headerlink anchors
        if element.name == 'a' and element.get('class') and 'headerlink' in element.get('class'):
            return
            
        # Skip aside elements (usually contain metadata)
        if element.name == 'aside':
            return
            
        # Handle different HTML elements
        if element.name == 'h1':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"# {text}")
            self.output_lines.append("")
            
        elif element.name == 'h2':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"## {text}")
            self.output_lines.append("")
            
        elif element.name == 'h3':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"### {text}")
            self.output_lines.append("")
            
        elif element.name == 'h4':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"#### {text}")
            self.output_lines.append("")
            
        elif element.name == 'h5':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"##### {text}")
            self.output_lines.append("")
            
        elif element.name == 'h6':
            text = self.get_clean_header_text(element)
            self.output_lines.append(f"###### {text}")
            self.output_lines.append("")
            
        elif element.name == 'p':
            # Check if this paragraph contains an image
            img = element.find('img')
            if img:
                self.process_image(img)
            else:
                # Check if this paragraph contains a code block (invalid HTML but happens)
                code_block = element.find('div', class_='highlight') or element.find('table', class_='highlighttable')
                if code_block:
                    # Extract text before the code block
                    text_before = ""
                    for child in element.children:
                        if child.name is None:  # Text node
                            text_before += str(child).strip()
                        elif child == code_block:
                            break
                        else:
                            text_before += child.get_text().strip()
                    
                    if text_before.strip():
                        self.output_lines.append(text_before.strip())
                    
                    # Process the code block
                    self.process_code_block(code_block)
                else:
                    text = self.get_text_content(element, preserve_formatting=True)
                    if text.strip():
                        # Check if this is followed by a code block
                        next_sibling = element.find_next_sibling()
                        if (next_sibling and 
                            ((next_sibling.name == 'div' and next_sibling.get('class') and 'highlight' in next_sibling.get('class', [])) or
                             (next_sibling.name == 'table' and next_sibling.get('class') and 'highlighttable' in next_sibling.get('class', [])))):
                            # This text is before a code block, add it without extra newline
                            # But check if it contains line numbers that should be filtered out
                            if "Request Body:" in text:
                                # Extract just the "Request Body:" part and ignore any line numbers
                                clean_text = "Request Body:"
                                self.output_lines.append(clean_text)
                            else:
                                self.output_lines.append(text)
                        else:
                            self.output_lines.append(text)
                            self.output_lines.append("")
                
        elif element.name == 'ul':
            self.process_list(element, ordered=False)
            self.output_lines.append("")
            
        elif element.name == 'ol':
            self.process_list(element, ordered=True)
            self.output_lines.append("")
            
        elif element.name == 'li':
            # This should be handled by process_list
            pass
            
        elif element.name == 'code' and element.parent.name != 'pre':
            # Inline code
            return f"`{self.get_text_content(element)}`"
            
        elif element.name == 'pre':
            self.process_code_block(element)
            
        elif element.name == 'div' and element.get('class') and 'highlight' in element.get('class', []):
            self.process_code_block(element)
            
        elif element.name == 'table' and element.get('class') and 'highlighttable' in element.get('class', []):
            self.process_code_block(element)
            
        elif element.name == 'img':
            self.process_image(element)
            
        elif element.name == 'a':
            return self.process_link(element)
            
        elif element.name == 'strong' or element.name == 'b':
            return f"**{self.get_text_content(element)}**"
            
        elif element.name == 'em' or element.name == 'i':
            return f"*{self.get_text_content(element)}*"
            
        else:
            # For other elements, process children
            for child in element.children:
                self.process_element(child)
    
    def get_clean_header_text(self, element):
        """Get header text without headerlink symbols."""
        # Remove headerlink elements
        for headerlink in element.find_all('a', class_='headerlink'):
            headerlink.decompose()
        
        # Also remove any anchor elements with name attributes
        for anchor in element.find_all('a'):
            if anchor.get('name'):
                # Keep the anchor but format it properly
                name = anchor.get('name')
                anchor.replace_with(f' <a name="{name}"></a>')
        
        return element.get_text().strip()
    
    def get_text_content(self, element, preserve_formatting=False):
        """Extract text content from element, optionally preserving inline formatting."""
        if not preserve_formatting:
            return element.get_text().strip()
        
        result = ""
        for child in element.children:
            if child.name is None:  # Text node
                result += str(child)
            elif child.name == 'code':
                result += f"`{child.get_text()}`"
            elif child.name == 'strong' or child.name == 'b':
                result += f"**{child.get_text()}**"
            elif child.name == 'em' or child.name == 'i':
                result += f"*{child.get_text()}*"
            elif child.name == 'a':
                href = child.get('href', '')
                text = child.get_text()
                if href and href.startswith('#'):
                    # This is a reference link, preserve the format
                    result += f"[{text}]({href})"
                elif href and not href.startswith('#'):
                    result += f"[{text}]({href})"
                elif child.get('name'):
                    # Handle anchor tags with names
                    name = child.get('name')
                    result += f'<a name="{name}"></a>'
                else:
                    result += text
            else:
                # Recursively process other elements to preserve nested formatting
                result += self.get_text_content(child, preserve_formatting=True)
        
        return result.strip()
    
    def process_list(self, list_element, ordered=False, indent_level=0):
        """Process ul or ol elements with proper indentation."""
        items = list_element.find_all('li', recursive=False)
        for i, item in enumerate(items):
            if ordered:
                prefix = f"{i + 1}. "
            else:
                prefix = "- "
            
            # Add indentation for nested lists
            indent = "  " * indent_level
            
            # Check if this item has nested lists
            nested_lists = item.find_all(['ul', 'ol'], recursive=False)
            
            if nested_lists:
                # Extract text content excluding nested lists
                item_copy = item.__copy__()
                for nested in item_copy.find_all(['ul', 'ol']):
                    nested.decompose()
                text = self.get_text_content(item_copy, preserve_formatting=True)
                
                if text.strip():
                    self.output_lines.append(f"{indent}{prefix}{text}")
                else:
                    # Empty list item with only nested lists
                    self.output_lines.append(f"{indent}{prefix}")
                
                # Process nested lists
                for nested_list in nested_lists:
                    self.process_list(nested_list, 
                                    ordered=(nested_list.name == 'ol'), 
                                    indent_level=indent_level + 1)
            else:
                # Simple list item without nested lists
                text = self.get_text_content(item, preserve_formatting=True)
                if text:
                    self.output_lines.append(f"{indent}{prefix}{text}")
    
    def process_code_block(self, element):
        """Process code blocks."""
        # Try to find the language from class names
        language = ""
        
        # Look for language in various places
        if element.get('class'):
            for cls in element.get('class'):
                if cls.startswith('language-'):
                    language = cls.replace('language-', '')
                    break
        
        # For highlighttable structure, find the actual code content
        code_content = ""
        
        # Try to find code in the table structure (common in syntax highlighted blocks)
        code_cell = element.find('td', class_='code')
        if code_cell:
            code_element = code_cell.find('code')
            if code_element:
                code_content = code_element.get_text()
            else:
                code_content = code_cell.get_text()
        else:
            # Fallback: find any code element, but completely skip line number containers
            for code_element in element.find_all('code'):
                # Check if this code element is inside a line number container
                parent = code_element.parent
                is_line_number = False
                while parent:
                    if parent.get('class') and any(cls in parent.get('class', []) for cls in ['linenos', 'linenodiv']):
                        is_line_number = True
                        break
                    parent = parent.parent
                
                if not is_line_number:
                    # Not in a line number container, use this code
                    code_content = code_element.get_text()
                    break
            
            # If we still don't have content, try to get text but completely skip line number elements
            if not code_content:
                # Get all text but skip elements with line number classes and their children
                all_text = ""
                for elem in element.find_all(text=True):
                    parent = elem.parent
                    skip = False
                    while parent:
                        if parent.get('class') and any(cls in parent.get('class', []) for cls in ['linenos', 'linenodiv']):
                            skip = True
                            break
                        parent = parent.parent
                    if not skip:
                        all_text += str(elem)
                code_content = all_text
        
        # Clean up the code content
        code_content = html.unescape(code_content)
        
        # Remove any remaining line number artifacts and clean up
        lines = code_content.split('\n')
        cleaned_lines = []
        for line in lines:
            # Skip lines that are just numbers (line numbers)
            if re.match(r'^\s*\d+\s*$', line):
                continue
            # Remove leading numbers that look like line numbers at start of line
            cleaned_line = re.sub(r'^\s*\d+\s+', '', line)
            # Also remove any standalone numbers that might be line numbers
            if re.match(r'^\s*\d+\s*$', cleaned_line):
                continue
            cleaned_lines.append(cleaned_line)
        
        code_content = '\n'.join(cleaned_lines).strip()
        
        # Additional cleanup: remove any text that looks like line number artifacts
        code_content = re.sub(r'\n\s*\d+\s*\n', '\n', code_content)
        code_content = re.sub(r'^\s*\d+\s*\n', '', code_content)
        
        # Remove any remaining isolated numbers that are likely line numbers
        lines = code_content.split('\n')
        final_lines = []
        for line in lines:
            # Skip lines that contain only numbers and whitespace
            if not re.match(r'^\s*\d+\s*$', line.strip()):
                # Also remove leading numbers from the first character of actual content
                cleaned_line = re.sub(r'^\d+([{\[])', r'\1', line)
                final_lines.append(cleaned_line)
        
        code_content = '\n'.join(final_lines).strip()
        
        if code_content:
            self.output_lines.append(f"```{language}")
            self.output_lines.append(code_content)
            self.output_lines.append("```")
            self.output_lines.append("")
    
    def process_image(self, img_element):
        """Process img elements."""
        src = img_element.get('src', '')
        alt = img_element.get('alt', '')
        
        if src:
            self.output_lines.append(f"![{alt}]({src})")
            self.output_lines.append("")
    
    def process_link(self, link_element):
        """Process a elements."""
        href = link_element.get('href', '')
        text = link_element.get_text()
        
        # Skip headerlinks and empty links
        if (link_element.get('class') and 'headerlink' in link_element.get('class')) or not text.strip():
            return ""
        
        if href and href.startswith('#'):
            # This is a reference link, preserve it
            return f"[{text}]({href})"
        elif href and not href.startswith('#'):
            return f"[{text}]({href})"
        elif link_element.get('name'):
            # Handle anchor tags
            name = link_element.get('name')
            return f'<a name="{name}"></a>'
        else:
            return text
    
    def clean_markdown(self, content):
        """Clean up the generated markdown."""
        lines = content.split('\n')
        cleaned_lines = []
        
        prev_line_empty = False
        for line in lines:
            line = line.rstrip()
            
            # Remove lines that are just symbols or artifacts
            if line in ['¶', '&para;'] or re.match(r'^\s*[¶&;]+\s*$', line):
                continue
            
            # Remove lines that are just numbers (likely line numbers)
            if re.match(r'^\s*\d+\s*$', line):
                continue
            
            # Remove lines that look like dates or metadata at the end
            if re.match(r'^\d{4}-\d{2}-\d{2}$', line):
                continue
                
            # Remove lines that are just commas or other artifacts
            if line in [',', '']:
                if line == '':
                    if not prev_line_empty:
                        cleaned_lines.append(line)
                    prev_line_empty = True
                continue
            
            # Remove excessive empty lines
            if not line:
                if not prev_line_empty:
                    cleaned_lines.append(line)
                prev_line_empty = True
            else:
                cleaned_lines.append(line)
                prev_line_empty = False
        
        # Remove trailing empty lines
        while cleaned_lines and not cleaned_lines[-1]:
            cleaned_lines.pop()
        
        return '\n'.join(cleaned_lines) + '\n' 