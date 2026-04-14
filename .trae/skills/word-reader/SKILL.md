---
name: "word-reader"
description: "Reads and extracts content from Word files (.doc, .docx). Invoke when user needs to read Word documents or extract Word content."
---

# Word Reader

This skill reads and extracts content from Microsoft Word files (.doc and .docx).

## When to Use

Invoke this skill when:
- User asks to read a Word document
- User wants to extract text from .doc or .docx files
- User needs to analyze Word file content

## Supported Formats

| Format | Method | Requirements |
|--------|--------|--------------|
| `.docx` | python-docx | `pip install python-docx` |
| `.doc` | win32com (Windows only) | Microsoft Word installed |

## Usage Instructions

### For .docx files (Recommended)

Use the `python-docx` library:

```python
from docx import Document

def read_docx(file_path: str) -> str:
    """Read content from a .docx file."""
    doc = Document(file_path)
    content = []
    for para in doc.paragraphs:
        if para.text.strip():
            content.append(para.text)
    
    # Also extract tables
    for table in doc.tables:
        for row in table.rows:
            row_text = [cell.text for cell in row.cells]
            content.append(" | ".join(row_text))
    
    return "\n".join(content)
```

### For .doc files (Windows only)

Use `win32com` with Microsoft Word:

```python
import win32com.client

def read_doc(file_path: str) -> str:
    """Read content from a .doc file using Microsoft Word."""
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    doc = word.Documents.Open(file_path)
    content = doc.Content.Text
    doc.Close()
    word.Quit()
    return content
```

## Implementation Steps

1. **Check file extension** - Determine if it's .doc or .docx
2. **Use appropriate method**:
   - For `.docx`: Use python-docx library
   - For `.doc`: Use win32com (requires Windows + MS Word)
3. **Extract content** - Get paragraphs, tables, and other elements
4. **Return formatted text** - Present content in readable format

## Dependencies

Install required packages:

```bash
# For .docx files
pip install python-docx

# For .doc files (Windows only)
pip install pywin32
```

## Example Workflow

When user asks to read a Word file:

1. Read the file using the appropriate method based on extension
2. Extract all text content including paragraphs and tables
3. Present the content in a structured, readable format
4. Optionally summarize or analyze the content as requested
