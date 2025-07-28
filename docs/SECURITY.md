# Security Policy

## Supported Versions

We actively support the following versions of Mumu-discord with security updates:

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < Latest| :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please follow these steps:

### Private Disclosure

**DO NOT** create a public GitHub issue for security vulnerabilities.

Instead, please:

1. **GitHub Security Advisories**: Use GitHub's private vulnerability reporting feature by going to the repository's Security tab and clicking "Report a vulnerability"
2. **Direct Contact**: Contact the repository maintainers through GitHub discussions or by mentioning @techpriests in a private repository (if you have access)
3. **Include**: 
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (if applicable)

### What to Expect

- **Acknowledgment**: We'll (hopefully) acknowledge receipt within 48 hours
- **Initial Response**: We'll try to provide an initial response within 5 business days
- **Updates**: We'll keep you informed of progress at least weekly
- **Resolution**: We aim to resolve critical vulnerabilities within 90 days

### Security Best Practices

#### For Users
- Keep your bot token secure and never share it publicly
- Use environment variables for sensitive configuration
- Regularly update to the latest version
- Review permissions granted to the bot

#### For Developers
- Never commit API keys or tokens to version control
- Use `.env` files for local development
- Follow the principle of least privilege for bot permissions
- Regularly audit dependencies for vulnerabilities

### Security Features

Our bot includes several security measures:

- **Environment Isolation**: Sensitive data stored in environment variables
- **API Rate Limiting**: Protection against API abuse
- **Guild Isolation**: Data separation between Discord servers
- **Input Validation**: Sanitization of user inputs
- **Error Handling**: Secure error messages that don't leak sensitive information

### Additional Resources

- [Discord Bot Security Best Practices](https://discord.com/developers/docs/topics/oauth2#bot-vs-user-accounts)
- [Python Security Guidelines](https://python.org/dev/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

---

**Note**: This documentation was written with AI (Claude Code) under human supervision.

Thank you for helping to keep Mumu-discord secure! 