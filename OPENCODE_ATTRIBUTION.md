# OpenCode reference and attribution

This implementation uses design ideas studied in the OpenCode repository:
https://github.com/anomalyco/opencode

Reference snapshot examined: `68510d9d6e5e3eb238f622625e5870874a8f3e8d`.

Relevant reference areas include the AI provider/route layer, session runner,
tool runtime, permission handling, retry behavior, context management, and tests.
The Hercules runtime files in this change are Python adaptations designed for
Hercules; they are not intended to be drop-in copies of OpenCode's TypeScript
implementation.

OpenCode is distributed under the MIT License. If future changes copy or adapt
substantial source code from OpenCode, retain the applicable copyright and
license notices and review all dependency licenses separately. See the upstream
repository's LICENSE file for the full terms.
