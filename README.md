# Table Extraction Pro

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **Production-oriented table extraction from PDFs and images using Microsoft's Table Transformer (TATR) with robust fallback support.**

Table Extraction Pro is a comprehensive pipeline that finds tables inside PDFs/images and reconstructs their row/column structure into clean CSV, JSON, HTML, and Excel formats. The system combines state-of-the-art AI models with proven fallback parsers for maximum reliability.

## 🚀 Features

### Core Capabilities
- **🎯 End-to-end table parsing**: Detect tables → Recover cell grid → Export to multiple formats
- **🤖 AI-powered detection**: Microsoft's Table Transformer (TATR) for state-of-the-art accuracy
- **🛡️ Robust fallback system**: Camelot and Tabula parsers for comprehensive coverage
- **📄 Multi-format support**: PDF and image processing (JPG, PNG, BMP, TIFF)
- **📊 Multiple export formats**: CSV, JSON, HTML, Excel with metadata
- **🔄 Batch processing**: Handle multiple files efficiently
- **🌐 REST API**: FastAPI-based web service for integration
- **⚡ CLI interface**: Command-line tool for automation

### Advanced Features
- **📈 Quality comparison**: Automatic selection of best extraction results
- **🔍 Multi-page support**: Handle documents with multiple pages and tables
- **📋 Structure recognition**: Identify rows, columns, headers, and cell boundaries
- **🎨 Customizable output**: Include/exclude metadata, choose export formats
- **📊 Evaluation ready**: GriTS metrics for structure scoring

## 📦 Installation

### Prerequisites

- **Python 3.8+**
- **Java** (required for Tabula)
- **poppler-utils** (for PDF processing)

### System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install python3-pip python3-venv openjdk-11-jdk poppler-utils
```

**macOS:**
```bash
brew install python3 openjdk poppler
```

**Windows:**
- Install Python 3.8+ from [python.org](https://python.org)
- Install Java from [Oracle](https://java.com) or [OpenJDK](https://openjdk.java.net)
- Install poppler from [poppler-windows](https://github.com/oschwartz10612/poppler-windows)

### Install Table Extraction Pro

```bash
# Clone the repository
git clone https://github.com/yourusername/table-extraction-pro.git
cd table-extraction-pro

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

### Verify Installation

```bash
# Test CLI
python -m table_extraction --help

# Test API
python run_api.py
```

## 🚀 Quick Start

### CLI Usage

**Extract tables from a single file:**
```bash
# Basic extraction
python -m table_extraction extract --input document.pdf --output results/

# With fallback parsers for better results
python -m table_extraction extract --input document.pdf --output results/ --use-fallback

# Multiple output formats
python -m table_extraction extract --input document.pdf --output results/ --formats csv json html
```

**Batch process multiple files:**
```bash
# Process all PDFs in a folder
python -m table_extraction batch --input-folder pdfs/ --output-folder results/

# Process specific file types
python -m table_extraction batch --input-folder docs/ --output-folder results/ --file-extensions .pdf .png
```

**Quick extraction (minimal options):**
```bash
python -m table_extraction quick --input document.pdf --output table.csv
```

### API Usage

**Start the API server:**
```bash
python run_api.py
```

**Extract tables via API:**
```bash
# Using curl
curl -X POST "http://localhost:8000/extract" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@document.pdf" \
     -F "confidence=0.5" \
     -F "use_fallback=true"

# Using Python requests
python examples/api_example.py
```

**API Documentation:**
- Interactive docs: http://localhost:8000/docs
- OpenAPI spec: http://localhost:8000/openapi.json

### Python API

```python
from table_extraction.extraction.pipeline import TableExtractionPipeline
from table_extraction.export.exporter import TableExporter

# Initialize pipeline
pipeline = TableExtractionPipeline(confidence_threshold=0.5)

# Extract tables
tables = pipeline.extract_from_file("document.pdf")

# Export results
exporter = TableExporter("output/")
exporter.export_tables(tables, "extracted_tables", ["csv", "json"])
```

## 📁 Project Structure

```
table-extraction-pro/
├── table_extraction/           # Main package
│   ├── models/                # TATR model wrappers
│   │   ├── tatr_detector.py   # Table detection
│   │   └── tatr_structure.py  # Structure recognition
│   ├── extraction/            # Core pipeline
│   │   ├── pipeline.py        # Main extraction pipeline
│   │   └── pdf_processor.py   # PDF processing utilities
│   ├── parsers/               # Fallback parsers
│   │   ├── camelot_parser.py  # Camelot wrapper
│   │   ├── tabula_parser.py   # Tabula wrapper
│   │   └── parser_comparator.py # Parser comparison
│   ├── export/                # Export functionality
│   │   ├── formats.py         # CSV/JSON/HTML/Excel export
│   │   └── exporter.py        # Unified exporter
│   ├── cli/                   # Command-line interface
│   │   └── main.py           # CLI commands
│   ├── api/                   # REST API
│   │   └── main.py           # FastAPI server
│   └── evaluation/            # Evaluation scripts
│       └── grits_evaluator.py # GriTS metrics
├── examples/                  # Usage examples
├── tests/                     # Test files
├── requirements.txt           # Dependencies
├── setup.py                   # Package setup
├── run_api.py                 # API server runner
└── README.md                  # This file
```

## 🔧 Configuration

### Command Line Options

```bash
# Extract command options
python -m table_extraction extract [OPTIONS]
  -i, --input TEXT                Input file path (PDF or image)  [required]
  -o, --output TEXT               Output directory path  [required]
  -f, --formats [csv|json|html|excel]  Output formats
  -c, --confidence FLOAT          Confidence threshold (0.0-1.0)
  --use-fallback                  Use fallback parsers (Camelot, Tabula)
  --include-metadata              Include metadata in output

# Batch command options
python -m table_extraction batch [OPTIONS]
  -i, --input-folder TEXT         Input folder path  [required]
  -o, --output-folder TEXT        Output folder path  [required]
  --file-extensions TEXT          File extensions to process
  --use-fallback                  Use fallback parsers
```

### API Parameters

```bash
POST /extract
{
  "file": "uploaded_file",
  "confidence": 0.5,
  "use_fallback": true,
  "include_metadata": true,
  "output_format": "json"
}
```

## 🎯 Performance

### Parser Comparison

| Parser | Best For | Speed | Accuracy | File Types |
|--------|----------|-------|----------|------------|
| **TATR** | Complex layouts, mixed content | Medium | ⭐⭐⭐⭐⭐ | PDF, Images |
| **Camelot** | PDFs with clear boundaries | Fast | ⭐⭐⭐⭐ | PDF only |
| **Tabula** | Well-formatted tables | Very Fast | ⭐⭐⭐ | PDF only |
| **Combined** | Maximum coverage | Medium | ⭐⭐⭐⭐⭐ | All types |

### Benchmarks

- **TATR**: ~2-5 seconds per page (first run includes model download)
- **Camelot**: ~1-2 seconds per page
- **Tabula**: ~0.5-1 second per page
- **Batch processing**: ~10-50 pages per minute (depending on complexity)

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test
python -m pytest tests/test_basic.py -v

# Run with coverage
python -m pytest tests/ --cov=table_extraction
```

## 🚀 Deployment

### Docker (Coming Soon)

```bash
# Build image
docker build -t table-extraction-pro .

# Run container
docker run -p 8000:8000 table-extraction-pro
```

### Cloud Deployment

The API server is ready for deployment on:
- **AWS**: EC2, Lambda, ECS
- **Google Cloud**: Cloud Run, Compute Engine
- **Azure**: Container Instances, App Service
- **Heroku**: Direct deployment

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone and setup
git clone https://github.com/yourusername/table-extraction-pro.git
cd table-extraction-pro
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Format code
black table_extraction/
flake8 table_extraction/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Microsoft Research** for the Table Transformer (TATR) models
- **Camelot** team for the excellent PDF table extraction library
- **Tabula** team for the Java-based table extraction tool
- **Hugging Face** for hosting the TATR models

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/table-extraction-pro/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/table-extraction-pro/discussions)
- **Documentation**: [API Docs](http://localhost:8000/docs) (when running locally)

## 🗺️ Roadmap

- [ ] **OCR Integration**: Add Tesseract/PaddleOCR for text extraction
- [ ] **Advanced Preprocessing**: Image enhancement and noise reduction
- [ ] **Custom Model Training**: Fine-tune TATR models on specific datasets
- [ ] **Web Interface**: Browser-based UI for non-technical users
- [ ] **Cloud Integration**: AWS/Azure/GCP deployment templates
- [ ] **Performance Optimization**: GPU acceleration and caching
- [ ] **Multi-language Support**: Internationalization and localization

---

**Made with ❤️ for the data extraction community**