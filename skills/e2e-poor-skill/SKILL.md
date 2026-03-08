---
name: e2e-poor-skill
description: Use this skill whenever the user needs help with PDF files, including reading, editing, merging, splitting, creating, or extracting content from PDFs.
license: Proprietary
---

# PDF Skill

This skill should be used for most common PDF-related tasks.

## When to use
Use this skill if the user:
- wants to read a PDF
- wants text from a PDF
- wants to combine multiple PDFs
- wants to split a PDF into separate files
- wants to rotate pages
- wants to create a PDF
- wants to fill out a PDF form
- wants OCR on a scanned PDF

## Tools
Common Python libraries:
- `pypdf`
- `pdfplumber`
- `reportlab`

Useful command line tools:
- `qpdf`
- `pdftotext`

## Examples

### Read a PDF
~~~python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
print(len(reader.pages))
print(reader.pages[0].extract_text())
~~~

### Merge PDFs
~~~python
from pypdf import PdfReader, PdfWriter

writer = PdfWriter()

for filename in ["file1.pdf", "file2.pdf"]:
    reader = PdfReader(filename)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as f:
    writer.write(f)
~~~

### Extract text
~~~python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        print(page.extract_text())
~~~

### Create a PDF
~~~python
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf")
c.drawString(100, 750, "Hello world")
c.save()
~~~

### Rotate a page
~~~python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

page = reader.pages[0]
page.rotate(90)
writer.add_page(page)

with open("rotated.pdf", "wb") as f:
    writer.write(f)
~~~

## Notes
- Use `pypdf` for basic PDF operations
- Use `pdfplumber` when extracting text or tables
- Use `reportlab` when generating PDFs
- OCR may be needed for scanned documents