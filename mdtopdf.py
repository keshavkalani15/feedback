#!/usr/bin/env python3
"""
Simple Markdown to PDF converter
Converts .md files to .pdf using markdown and xhtml2pdf libraries
"""

import sys
import os
from pathlib import Path
import markdown
from xhtml2pdf import pisa
from io import BytesIO


def convert_md_to_pdf(md_file, pdf_file=None):
    """
    Convert a markdown file to PDF.
    
    Args:
        md_file (str): Path to the markdown file
        pdf_file (str): Path to save the PDF (optional, defaults to same name with .pdf extension)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Convert path to Path object
        md_path = Path(md_file)
        
        # Check if markdown file exists
        if not md_path.exists():
            print(f"Error: Markdown file '{md_file}' not found.")
            return False
        
        # Set output PDF path
        if pdf_file is None:
            pdf_file = md_path.with_suffix('.pdf')
        
        pdf_path = Path(pdf_file)
        
        # Read markdown file
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown.markdown(md_content, extensions=['extra', 'codehilite'])
        
        # Add basic CSS styling
        css_string = """
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            line-height: 1.6;
            color: #333;
        }
        h1, h2, h3 { color: #2c3e50; margin-top: 20px; }
        code { background-color: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: 'Courier New', monospace; }
        pre { background-color: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }
        blockquote { border-left: 4px solid #999; margin: 0; padding-left: 10px; color: #666; }
        table { border-collapse: collapse; width: 100%; margin: 10px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f9f9f9; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        """
        
        # Create complete HTML document
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Document</title>
            <style>{css_string}</style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        
        # Convert HTML to PDF using xhtml2pdf
        with open(pdf_path, 'wb') as output_pdf:
            pisa.CreatePDF(full_html, output_pdf)
        
        print(f"✓ Successfully converted '{md_file}' to '{pdf_file}'")
        return True
    
    except Exception as e:
        print(f"Error converting markdown to PDF: {str(e)}")
        return False


def main():
    """Main function to handle command-line usage"""
    if len(sys.argv) < 2:
        print("Usage: python mdtopdf.py <markdown_file> [output_pdf_file]")
        print("\nExample:")
        print("  python mdtopdf.py document.md")
        print("  python mdtopdf.py document.md output.pdf")
        sys.exit(1)
    
    md_file = sys.argv[1]
    pdf_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = convert_md_to_pdf(md_file, pdf_file)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
