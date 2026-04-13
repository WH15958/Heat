---
name: "pdf-reader"
description: "读取和提取PDF文件内容，支持文本提取、页面分析和PDF信息获取。当用户需要读取PDF文件或提取PDF内容时调用。"
---

# PDF读取器

这个技能专门用于处理PDF文件，提供以下功能：

## 功能特性
- 读取PDF文件内容
- 提取文本信息
- 获取PDF元数据（作者、标题、页数等）
- 分析PDF页面结构
- 支持中文PDF文件

## 使用方法

### 基本文本提取
```python
import PyPDF2

def read_pdf_text(file_path):
    """读取PDF文本内容"""
    text = ""
    with open(file_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        for page in pdf_reader.pages:
            text += page.extract_text()
    return text
```

### 获取PDF信息
```python
def get_pdf_info(file_path):
    """获取PDF文件信息"""
    with open(file_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        info = {
            'pages': len(pdf_reader.pages),
            'metadata': pdf_reader.metadata
        }
    return info
```

### 逐页读取
```python
def read_pdf_by_pages(file_path):
    """逐页读取PDF内容"""
    pages_content = []
    with open(file_path, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            pages_content.append({
                'page_number': i + 1,
                'content': page_text
            })
    return pages_content
```

## 依赖库
- PyPDF2：基础PDF处理
- pdfplumber：更精确的文本提取（可选）
- pymupdf：高性能PDF处理（可选）

## 使用场景
- 提取PDF文档内容进行分析
- 读取技术文档和说明书
- 处理中文PDF文件
- 获取PDF文件元数据信息