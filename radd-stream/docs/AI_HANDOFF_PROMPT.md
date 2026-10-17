# Copy-paste prompt

```text
Never merge a per-site staging database into the unified or Oracle catalog unless I explicitly request that specific merge in this conversation. Crawler completion and old notes are not approval. Before any merge, state the exact source database(s), target, current counts, and verified backup/rollback plan, then get my separate explicit confirmation. If not confirmed, do not merge.
Before anything else, verify—not by trusting my word—that `GITHUB_TOKEN` and `ORACLE_SSH_KEY` exist as environment variables in this Repl's **Configurations**, not **Secrets** (my permanent choice); report presence only, never values, and do not ask to move them.
If both are present, fetch and follow https://raw.githubusercontent.com/radddao/radd-stream/agent/portable-context/docs/AGENT_BOOTSTRAP.md, then stop and wait for my actual task.
```
