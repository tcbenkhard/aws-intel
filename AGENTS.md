# AGENTS.md

## Project Overview

This repository contains a command-line application that assists users with
retrieving information from AWS.

Keep the tool focused, predictable, and safe. Prefer read-only AWS operations
unless a feature explicitly requires a mutation. Make AWS account, region, and
credential assumptions visible to the user.

## Engineering Principles

- Follow SOLID principles. Give each module, class, function, and component one
  clear responsibility.
- Follow DRY where it improves maintainability. Extract genuinely shared
  behavior, but do not create abstractions for coincidental similarity.
- Prefer readable, explicit code over clever abstractions or compressed logic.
- Keep dependencies flowing toward stable domain interfaces. Isolate AWS SDK,
  CLI framework, filesystem, and environment access behind clear boundaries.
- Favor small, composable functions and dependency injection over global state.

## Project Structure

- Split components into their own files; prefer one component per file.
- Group files by feature or responsibility rather than creating broad utility
  modules.
- Keep CLI argument parsing and presentation separate from application logic.
- Keep AWS client calls separate from data transformation and output rendering.
- Use shared helpers only when they have a cohesive, well-defined purpose.
- Avoid catch-all files such as `utils`, `helpers`, or `common`.

## CLI Behavior

- Use the command structure `awsi <utility> <options>`. Each AWS information
  operation must be implemented as a utility subcommand, for example:
  `awsi get-security-group-tree sg-1239213912038`.
- Use kebab-case utility names that clearly describe the operation.
- Provide useful `--help` text and actionable error messages.
- Validate arguments before making AWS requests.
- Keep command output stable and suitable for scripting.
- Always include column names when command output presents tabular information.
- Send requested data to standard output and diagnostics to standard error.
- Use meaningful exit codes and return a non-zero code on failure.
- Support non-interactive use; do not prompt unless the command clearly opts
  into interactive behavior.
- Never print credentials, tokens, secrets, or sensitive environment values.

## AWS Integration

- Use the standard AWS credential and region resolution mechanisms.
- Do not embed credentials, account IDs, regions, or resource identifiers in
  source code.
- Make the active AWS profile, account, and region clear when ambiguity could
  cause mistakes.
- Request only the permissions needed for each operation.
- Handle pagination explicitly when AWS APIs paginate results.
- Handle throttling, transient failures, missing credentials, authorization
  errors, and unavailable regions with clear messages.
- Keep AWS SDK response types at the integration boundary. Convert them into
  application-owned models before using them elsewhere.
- Mock AWS boundaries in unit tests; tests must not contact live AWS services
  unless they are explicitly marked as integration tests.

## Quality Standards

- Add or update tests for behavior changes and bug fixes.
- Test successful results, empty results, pagination, invalid input, and
  relevant AWS error paths.
- Keep tests deterministic and independent of a developer's local AWS
  configuration.
- Use the project's formatter, linter, type checker, and test runner before
  considering work complete.
- Preserve backward compatibility for CLI flags and output formats unless a
  breaking change is intentional and documented.

## Change Guidelines

- Make the smallest cohesive change that fully solves the task.
- Follow established project patterns once they exist.
- Do not introduce a dependency when a small, clear implementation using the
  standard library or an existing dependency is sufficient.
- Update user-facing documentation when commands, flags, configuration, or
  output change.
- Record assumptions and significant tradeoffs in code comments or
  documentation; comments should explain why, not restate what the code does.
