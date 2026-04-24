# Security Policy

## Reporting a Vulnerability

The EGM Downloader team takes security seriously. We appreciate your efforts to responsibly disclose your findings.

### How to Report

**Please do NOT open a public issue for security vulnerabilities.**

Instead, report security concerns through one of these methods:

#### Option 1: Email (Preferred)
Send details to: **contact@egerena.com**

#### Option 2: GitHub Private Vulnerability Reporting
Use GitHub's [private vulnerability reporting feature](https://github.com/egmtm/EGM-Downloader/security/advisories/new)

### What to Include

Please include the following information in your report:

- **Description** - Clear description of the vulnerability
- **Steps to Reproduce** - Detailed steps to reproduce the issue
- **Impact** - What could an attacker accomplish?
- **Affected Versions** - Which versions are vulnerable?
- **Suggested Fix** - (Optional) If you have ideas for a fix
- **Your Contact** - How we can reach you for follow-up

### Example Report

```
Subject: [SECURITY] Potential XSS vulnerability in filename display

Description:
User-supplied filenames are displayed in the UI without proper sanitization,
potentially allowing XSS attacks through malicious filenames.

Steps to Reproduce:
1. Download a file with filename: <script>alert('xss')</script>.mp4
2. Observe the filename displayed in the download list
3. Script executes in the context of the application

Impact:
An attacker could craft a malicious URL that, when downloaded, executes
arbitrary JavaScript in the application context.

Affected Versions:
v0.91 Build 92 and earlier

Suggested Fix:
Sanitize filenames using DOMPurify or similar before displaying in UI.
```

## Response Timeline

- **Acknowledgment** - Within 48 hours of receiving your report
- **Initial Assessment** - Within 1 week of acknowledgment
- **Status Updates** - Every 2 weeks until resolution
- **Fix Development** - Depends on severity (critical issues prioritized)
- **Disclosure** - Coordinated with reporter after fix is released

## Security Update Process

When a security vulnerability is confirmed:

1. **Private Fix** - We develop a fix in a private branch
2. **Testing** - Thorough testing to ensure fix works and doesn't break functionality
3. **Release** - Emergency release with security patch
4. **Disclosure** - Public disclosure after users have time to update (typically 7-14 days)
5. **Credit** - Reporter credited in release notes (unless they prefer to remain anonymous)

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.91.x  | ✅ Yes    |
| < 0.91  | ❌ No     |

We only provide security updates for the latest stable release. Users on older versions should upgrade to the latest version.

## Security Best Practices for Users

### General Recommendations

- ✅ **Download from official sources only** - https://egerena.com or https://github.com/egmtm/EGM-Downloader
- ✅ **Keep software updated** - Enable auto-updates (Windows/Mac) or check regularly (Linux)
- ✅ **Verify checksums** - When available, verify file integrity
- ✅ **Use antivirus software** - Keep your system protected
- ✅ **Review permissions** - Understand what access the application requests

### What EGM Downloader Does NOT Do

- ❌ We never ask for passwords (except your own ZIP password if you set one)
- ❌ We never collect personal information
- ❌ We never send your download history to any server
- ❌ We never execute arbitrary code from downloaded videos
- ❌ We never access files outside the download directory

### Red Flags (Potential Scams)

If you encounter any of the following, you may have downloaded a fake or compromised version:

- 🚫 Requests for credit card information
- 🚫 Asks for admin/root password on every launch
- 🚫 Shows unexpected ads or pop-ups
- 🚫 Tries to install additional software without permission
- 🚫 Requests access to your email or social media accounts
- 🚫 Has a different icon or branding than shown on official site

**If you see any of these, DO NOT USE and report to contact@egerena.com**

## Known Security Considerations

### Third-Party Dependencies

EGM Downloader relies on several third-party components:

- **yt-dlp** - Download engine (updated via plugin system)
- **FFmpeg** - Media processing (updated via plugin system)
- **Electron** - Desktop framework (updated with app releases)

We monitor security advisories for these dependencies and release updates promptly when vulnerabilities are discovered.

### Network Activity

EGM Downloader makes network requests to:

- **Video hosting sites** - To download requested content
- **egerena.com** - To check for updates (Windows/Mac only)
- **Package managers** - To download yt-dlp and FFmpeg updates

All network activity is related to core functionality. We do not send telemetry or analytics.

### File System Access

The application:

- ✅ Reads/writes to the download directory you specify
- ✅ Reads/writes configuration in app data directory
- ✅ Reads/writes temporary files during processing

It does NOT:

- ❌ Access files outside designated directories
- ❌ Modify system files
- ❌ Install drivers or kernel modules
- ❌ Access webcam, microphone, or location

## Vulnerability Disclosure Policy

We follow **coordinated disclosure** (also known as responsible disclosure):

1. Reporter privately notifies us
2. We confirm and develop a fix
3. We release the fix
4. We publicly disclose the vulnerability after users have time to update
5. We credit the reporter (unless they prefer anonymity)

We ask that reporters:

- Give us reasonable time to fix the issue before public disclosure (typically 90 days)
- Do not exploit the vulnerability beyond what's needed to demonstrate it
- Do not access or modify other users' data
- Act in good faith

## Bug Bounty Program

We currently **do not** have a formal bug bounty program. However:

- We deeply appreciate security researchers' efforts
- We credit reporters in release notes and CREDITS.md
- We may offer rewards on a case-by-case basis for critical vulnerabilities

## Security Acknowledgments

We'd like to thank the following individuals for responsibly disclosing security issues:

*(No vulnerabilities reported yet)*

---

## Legal & Responsible Use

EGM Downloader is a tool designed for lawful purposes. Users are responsible for ensuring their use complies with copyright laws, platform terms of service, and applicable regulations.

**For complete information on legal and responsible use, please see the [Legal & Responsible Use](README.md#%EF%B8%8F-legal--responsible-use) section in the README.**

---

## Contact

For any security concerns or questions about this policy:

**Email:** contact@egerena.com  
**GitHub:** [@egmtm](https://github.com/egmtm)

---

**Thank you for helping keep EGM Downloader and its users safe!** 🔒
