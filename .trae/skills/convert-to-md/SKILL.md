---
name: "convert-to-md"
description: "Converts PDF/DOCX/PPTX/XLSX/HTML files to standard Markdown. Invoke when user wants to convert documents to Markdown format."
---

# Convert to Markdown

Convert various document formats (PDF, DOCX, PPTX, XLSX, HTML) to standard Markdown.

## Usage

```
/convert-to-md <file_or_folder_path>
```

## Supported Formats

| Format | Extension | Tool Priority |
|--------|----------|---------------|
| PDF | `.pdf` | markitdown -> pandoc |
| Word | `.docx` | markitdown -> pandoc |
| PowerPoint | `.pptx` | markitdown -> pandoc |
| Excel | `.xlsx` | markitdown -> pandoc |
| HTML | `.html`, `.htm` | pandoc |

## Conversion Logic

1. **First try `markitdown`** (better extraction for complex documents)
2. **Fallback to `pandoc`** if markitdown is unavailable
3. Output file saved in the **same directory** as the source file
4. Filename: `<original_name>.md`

## Examples

**Single file:**
```
/convert-to-md document.pdf
/convert-to-md report.docx
```

**Batch (entire folder):**
```
/convert-to-md ./documents/
```

## Error Handling

- If neither tool is installed, display installation instructions
- For password-protected files, skip and report error
- For empty files, create empty `.md` file

## Notes

- Tables in Excel/Word are preserved as Markdown tables
- Images are not extracted (only text content)
- PDF text extraction quality depends on the PDF (scanned images may not convert well)
