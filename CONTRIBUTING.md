# Contributing to Table Extraction Pro

Thank you for your interest in contributing to Table Extraction Pro! We welcome contributions from the community.

## 🚀 Getting Started

### Development Setup

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/yourusername/table-extraction-pro.git
   cd table-extraction-pro
   ```

3. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install in development mode**:
   ```bash
   pip install -e ".[dev]"
   ```

5. **Run tests** to ensure everything works:
   ```bash
   python -m pytest tests/ -v
   ```

## 📝 Types of Contributions

### 🐛 Bug Reports
- Use the GitHub issue tracker
- Include steps to reproduce
- Provide system information (OS, Python version, etc.)
- Include error messages and logs

### ✨ Feature Requests
- Use the GitHub issue tracker
- Describe the feature clearly
- Explain the use case and benefits
- Consider implementation complexity

### 🔧 Code Contributions
- Fork the repository
- Create a feature branch: `git checkout -b feature/amazing-feature`
- Make your changes
- Add tests for new functionality
- Ensure all tests pass
- Submit a pull request

## 🧪 Testing

### Running Tests
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_basic.py -v

# Run with coverage
python -m pytest tests/ --cov=table_extraction

# Run linting
flake8 table_extraction/
black table_extraction/
```

### Writing Tests
- Add tests for new functionality
- Follow the existing test structure
- Use descriptive test names
- Test both success and failure cases

## 📋 Code Style

### Python Style
- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for functions and classes
- Keep functions small and focused

### Formatting
```bash
# Format code with black
black table_extraction/

# Check style with flake8
flake8 table_extraction/
```

### Documentation
- Update README.md for user-facing changes
- Add docstrings for new functions/classes
- Update API documentation if needed

## 🔄 Pull Request Process

1. **Create a feature branch** from `main`
2. **Make your changes** with clear commit messages
3. **Add tests** for new functionality
4. **Run tests** and ensure they pass
5. **Update documentation** if needed
6. **Submit a pull request** with a clear description

### Pull Request Template
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or clearly documented)
```

## 🏗️ Project Structure

```
table-extraction-pro/
├── table_extraction/     # Main package
├── tests/               # Test files
├── examples/            # Usage examples
├── docs/               # Documentation
└── scripts/            # Utility scripts
```

## 🎯 Areas for Contribution

### High Priority
- **OCR Integration**: Add text extraction from table cells
- **Performance Optimization**: Improve extraction speed
- **Error Handling**: Better error messages and recovery
- **Documentation**: Improve examples and tutorials

### Medium Priority
- **New Export Formats**: Add more output formats
- **Web Interface**: Browser-based UI
- **Cloud Deployment**: Docker and cloud templates
- **Internationalization**: Multi-language support

### Low Priority
- **Advanced Preprocessing**: Image enhancement
- **Custom Models**: Training pipeline
- **Analytics**: Usage tracking and metrics

## 📞 Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and ideas
- **Code Review**: All PRs are reviewed by maintainers

## 🏆 Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes
- GitHub contributors page

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Table Extraction Pro! 🎉
