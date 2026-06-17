# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add opt-in Telegram channel that mirrors desktop alerts via the Telegram Bot API (a285980)

### Changed

- Route diagnostics through the logging module instead of print (d34002d)

### Security

- Prevent script and command injection in the macOS and Windows backends (b906958)

## [0.1.1] - 2025-07-08

### Added

- Add real-time Claude session monitoring for watch mode (80d4d8c)

## [0.1.0] - 2025-07-07

### Added

- Add cross-platform desktop notifications for macOS, Linux, and Windows (737a2a7)
- Add CLI with send, watch, hook, check, and config commands (737a2a7)
- Add Claude Code hook integration with project identification (737a2a7)
