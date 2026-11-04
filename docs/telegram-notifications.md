# Telegram workflow notifications

Faseela can send a Telegram message when one of the repository's GitHub Actions
workflows finishes. Notifications cover:

- **CI** — recipe and repository regression checks.
- **Build packages** — package selection, building, and publishing.
- **Build packages (experimental)** — the manual experimental build.

The notification reports the overall workflow result, repository, branch, short
commit ID, trigger, actor, individual job results, and a direct link to the run.
Messages use Telegram HTML formatting and escape all values supplied by GitHub.

## Configure the bot

1. Create a bot with Telegram's **@BotFather** and copy its API token.
2. Open a chat with the bot and send **/start**. For a group, add the bot and
   send a message in that group.
3. Obtain the destination chat ID from the message.chat.id field returned by
   the Telegram Bot API getUpdates method. Keep the bot token private.
4. In the GitHub repository, open **Settings → Secrets and variables → Actions**
   and add these repository secrets:

   | Secret | Value |
   | --- | --- |
   | TELEGRAM_BOT_TOKEN | Token issued by @BotFather |
   | TELEGRAM_CHAT_ID | The destination user's or group's chat ID |

Do not commit either value to the repository, workflow files, logs, or issues.
If either secret is absent (for example, on a fork pull request), the notification
step is skipped and the workflow continues normally.

## Reliability and testing

Telegram delivery is best-effort: an API/network failure produces a GitHub
Actions warning but never changes the build or publishing result. Job outcomes
are passed to the notifier explicitly, so a skipped build job (such as a
successful dry run or an empty package selection) is not reported as a failure.

Run the offline regression tests with:

    python3 -I scripts/test-telegram-notify.py

No Telegram account, bot token, or network access is needed for the tests.
