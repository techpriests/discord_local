# Contributing to Mumu-discord

Thank you for your interest in contributing! We welcome contributions from developers of all skill levels.

## Quick Start

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/techpriests/mumu-discord.git
   cd mumu-discord
   ```
3. **Create a feature branch** from `develop`:
   ```bash
   git checkout develop
   git checkout -b feature/your-feature-name
   ```
4. **Set up development environment**:
   ```bash
   poetry install
   poetry run pre-commit install
   ```

## Development Guidelines

### Code Style

We use several tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **Ruff**: Linting
- **MyPy**: Type checking
- **Pre-commit**: Automated checks

Run all checks before committing:
```bash
poetry run black src/
poetry run isort src/
poetry run ruff check src/
poetry run mypy src/
```

### Testing

- Write tests for new features using `pytest`
- Maintain or improve test coverage
- Run tests before submitting:
  ```bash
  poetry run pytest
  poetry run pytest --cov=src  # With coverage
  ```

### Documentation

- Update docstrings for new functions/classes
- Update README.md if adding new features
- Update CLAUDE.md for architectural changes
- Follow Google-style docstrings

## Project Structure

```
src/
├── bot.py                 # Main bot entry point
├── commands/              # Command cogs
│   ├── base.py           # Base command class
│   ├── information.py    # Info commands
│   ├── entertainment.py  # Fun commands
│   └── ...
├── services/              # Business logic
│   ├── api/              # External API integrations
│   ├── memory_db.py      # Data persistence
│   └── message_handler.py
└── utils/                 # Shared utilities
    ├── constants.py      # Configuration constants
    └── ...
```

## Types of Contributions

### Bug Reports

Use the bug report template and include:
- Clear description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Python version, OS, etc.)
- Relevant logs or error messages

### Feature Requests

- Check existing issues first
- Describe the feature and its use case
- Consider implementation complexity
- Discuss with maintainers before starting large features

### Code Contributions

#### New Commands
1. Create command in appropriate cog file
2. Add to both slash and prefix command handlers
3. Include comprehensive error handling
4. Add tests for the new functionality
5. Update documentation

#### API Integrations
1. Follow the existing service pattern in `src/services/api/`
2. Extend base classes for consistency
3. Implement proper rate limiting
4. Add error handling and fallbacks
5. Include tests for API interactions

#### Bug Fixes
1. Create a test that reproduces the bug
2. Fix the issue
3. Ensure the test now passes
4. Update documentation if needed

## Commit Guidelines

### Commit Messages
Use conventional commits format:
```
type(scope): description

[optional body]

[optional footer]
```

Examples:
```
feat(commands): add weather command
fix(memory): resolve guild isolation bug
docs: update installation instructions
test: add tests for exchange rate service
```

### Branch Naming
- `feature/command-name` - New features
- `fix/issue-description` - Bug fixes
- `docs/section-name` - Documentation updates
- `refactor/component-name` - Code refactoring

## Pull Request Process

1. **Update your branch** with latest `develop`:
   ```bash
   git checkout develop
   git pull upstream develop
   git checkout your-feature-branch
   git rebase develop
   ```

2. **Ensure all checks pass**:
   ```bash
   poetry run pytest
   poetry run mypy src/
   poetry run ruff check src/
   ```

3. **Create PR** against `develop` branch with:
   - Clear title and description
   - Reference related issues
   - Include testing instructions
   - Screenshots for UI changes

4. **Address review feedback** promptly
5. **Squash commits** if requested

## Recognition

Contributors will be:
- Added to the Contributors section
- Mentioned in release notes for significant contributions
- Invited to join the maintainers team for ongoing contributors

## Questions?

- **General questions**: Open a GitHub Discussion
- **Quick questions**: Comment on relevant issues
- **Security concerns**: See [SECURITY.md](SECURITY.md)

## Resources

- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Discord API Documentation](https://discord.com/developers/docs)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [Poetry Documentation](https://python-poetry.org/docs/)

---

**Note**: This documentation was written with AI (Claude Code) under human supervision.

Happy coding! 