# Security Policy

## Supported versions

Security fixes are provided for the latest release line only.

| Version | Supported |
| --- | --- |
| 1.6.x | Yes |
| 1.5.x and earlier | No |

## Reporting a vulnerability

Please do not disclose vulnerability details in a public issue.

Use the repository's **Security → Report a vulnerability** form to submit a private report. If private vulnerability reporting is not available yet, open an issue containing only a request for private contact and no technical details.

Include the affected version, reproduction steps, impact, and any suggested mitigation. You should receive an initial acknowledgement within seven days. Please allow a reasonable remediation period before public disclosure.

## Security model

Sharing Board is designed for temporary transfers between devices on a trusted local network. It is not an Internet-facing storage or multi-tenant service.

- Text, file contents, file metadata, nicknames, and avatars are encrypted in the browser.
- The server can observe connection metadata, room identifiers, ciphertext sizes, file sizes, chunk counts, and timing.
- Anyone with the complete invitation URL can join its room; there is no separate account or authorization layer.
- The bundled certificate is self-signed and provides transport encryption without public-CA identity assurance.
- Do not expose the service directly to the public Internet or use it for high-assurance classified data.
