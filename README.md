# Archive-Sync Engine (for Discord & Fluxer)

Archive-Sync Engine can _archive_ (import), _export_, and _migrate_ (synchronizing) servers from Discord Chat to [Fluxer](https://github.com/fluxerapp/fluxer) chat. Or from Fluxer Server to Fluxer.

## No Regrets Walking Away from Discord

Dear Discord, the Archive Engine team has a [message for you](https://c.tenor.com/dq8yuzNDkWkAAAAd/tenor.gif).

# Running the Program

Most common usage: If you want to import from an origin source (such as Discord) and export to a target destination, you will need to create two bots.
- _To import from an origin source_, you will need to create bot on that origin source (such as Discord). This will allow you to import into an Archive.
- _To export to a target destination_, you will need to (1) have imported already into an Archive, and (2) create a bot on the target destination (such as Fluxer or other supported chat services).

This will require saving some info to files (guided steps below), running the setup script, then you may execute the full program.

See Usage section.

## Pre-requisites

Python 3.11 or later installed on your system.

## Discord Bot Setup

To enable the migration program to interact with your Discord server, your Discord bot needs specific permissions.

Follow these steps:

1.  **Build a Bot / Create a Bot Application:**
    * Go to the [Discord Developer Portal](https://discord.com/developers/applications).
    * Log in and click on "Build a Bot".
    * Click the "New Application" button.
      * If you receive an error message, try again without being on a VPN.  
    * Give your application a name and create it.
    * Navigate to the "Bot" tab on the left sidebar.
    * Click "Add Bot" and confirm.

2.  **Copy Your Bot Token:**
    * Under the "Bot" tab, find the "TOKEN" section.
    * Click "Reset Token" if needed, then copy the token value.
        * THIS IS NOT YOUR CLIENT SECRET. Make sure to copy THE TOKEN, ***not*** the client secret.
    * **Create a file named `discord_token.token`** (or the name specified in your `config.yaml` under `discord:token_file`) in the same directory as your migration script.
    * Paste the copied token into this file and save it. **Ensure there are no extra spaces or newlines.**

3.  **Enable Privileged Gateway Intents:**
    * Still on the "Bot" tab, scroll down to the "Privileged Gateway Intents" section.
    * Enable the **`Message Content Intent`** toggle. This is crucial for the bot to read message content and attachments.

4.  **Set Bot Permissions (OAuth2 URL Generator):**
    * Navigate to the "OAuth2" tab on the left sidebar, then select "URL Generator".
    * Under the **"SCOPES"** section, select:
        * `bot`
    * A new section titled **"BOT PERMISSIONS"** will appear. In this section, select the following permissions:
        * `View Channels`
        * `Read Message History`
    * Scroll to the very bottom of this very. A URL will have been generated. Copy the generated URL.

5.  **Invite the Bot to Your Server:**
    * Paste the copied URL into your web browser.
    * Select the Discord server you wish to migrate from (you must have "Manage Server" permissions on this server).
    * Authorize the bot.

## Fluxer Bot Setup

To enable the migration program to interact with your Fluxer server, create a Fluxer bot and grant it specific permissions. Follow these steps:


1.  **Login:** Open the [Fluxer](https://web.fluxer.app/) app and sign in.

2.  **Create a Bot Application:**
    * Go to User Settings → Developers → Applications. 
    * This is done by finding your user Avatar and nearby should be a Gear-icon. Click this gear-icon to access the Settings.
    * From there click the button 'Create Application'. Give the application a name.

3.  **Copy Your Bot Token:**
    * Find the section labeled "Secrets & Tokens" tab, find the "Bot token" section.
    * Click "Regenerate" button if needed, then copy the token value.
        * This seems necessary after first creating your Application regardless.
        * THIS IS NOT YOUR CLIENT SECRET. Make sure to copy THE TOKEN, ***not*** the client secret.
    * **Create a file named `fluxer_token.token`** (or the name specified in your `config.yaml` under `fluxer:token_file`) in the same directory as your migration script.
    * Paste the copied token into this file and save it. **Ensure there are no extra spaces or newlines.**


4.  **Enable Permissions:**
    * Still on the "Application" tab, scroll down to the "OAuth2 URL Builder" section.
    * Select `bot' checkbox. A new section titled **"BOT PERMISSIONS"** will appear. In this section, select the following permissions:
      * `Manage Channels`
      * `Create Emoji & Stickers`
      * `Manage Emoji & Stickers`
      * `View Channel`
      * `Send Messages`
      * `Manage Messages`
      * `Pin Messages`
      * `Embed Links`
      * `Attach Files`
      * `Read Message History`
      * `Add Reactions`
    * Scroll to the very bottom of this very. A `Authorize URL` will have been generated. Copy the generated URL.
    * NOTE: After selecting the minimum `bot` step, more permissions can be granted later within a target server.
    
5.  **Invite the Bot to Your Server:**
    * In your web browser, open a new tab and paste the copied `Authorize URL` into the address bar. Press ENTER to go to the link.
    * Select the Fluxer server you wish to add the Bot to, in order to migrate content into there.(Your own user must have "Manage Server" permissions on this server).
    * Authorize the bot to be added.

By following these instructions, your bots will have the necessary access to perform the migration tasks.

## Origin-Server and Target-Server Setup


### Copy the Discord Server Channel ID

Origin server:

1. Log into https://discord.com/channels/
1. On the left side of the Discord Chat website, there is a sidebar. It displays the icons for servers the user (or bot) is a member of.
1. Navigate to the server by Left-clicking the original server.
1. Right-click on whatever is the original channel.
1. From the menu, select 'Copy Server Info', then select 'Copy Server ID'.
  - TROUBLESHOOTING: If you do not see the 'Copy Server ID' menu option, you may need to enable `Developer Mode` for your Discord account. 
    To enable Developer Mode, for Desktop and Web:
      1. Click the gear icon (User Settings) next to your username at the bottom-left. 
      1. Scroll down the left sidebar and select Advanced. 
      1. Toggle the switch next to Developer Mode to the on position (it will turn blue).

Store this server ID in the `config.yaml` file, in the `guild_id: ` section.

### Copy the Fluxer Server Channel ID

Target server:

1. Log into https://web.fluxer.app/
1. On the left side of the Fluxer Chat website, there is a sidebar. It displays the icons for servers the user (or bot) is a member of.
1. Navigate to the server by Left-clicking the target server.
1. Right-click on whatever is the target channel.
1. From the menu, select 'Copy Community ID'.

Store this server ID in the `config.yaml` file, in the `server_id: ` section.

### Optional: Enable Masquerading

WARNING: The masquerade feature will allow the migration tool to perform actions WITH YOUR PERSONAL USER ACCOUNT. Be very careful and do not share your token with anyone unless you trust them!

To enable the Masquerade feature, do the following: 

In your web-browser:
1. Go to `web.fluxer.app`
1. Open the web-developer console. Do this by pressing Ctrl+Shift+I or by going to Menu -> More Tools -> Developer Console.
1. Go to the 'Network' tab.
1. In the Filter, enter 'api'
1. From the type-buttons next to the Filter input, select 'Fetch/XHR'
1. Now in the Fluxer chat section, send a message to some channel. It doesn't matter what the message is or where you send it.)
1. In the web-developer section, you will see an entry appear labeled 'messages'. Click on this.
1. The display view will change, showing specific details of the 'messages' entry.
1. From the 'Headers' section, scroll down to the section for 'Request header`.
1. Find the line labeled 'Authorization', and copy the value next to it. This is your Masquerade token.
1. Save it into a specific file with the .token extension.
1. Edit your config.yaml to reflect your username and your masquerade token file.

#### Example config.yaml masquerade configuration

FIXME: DOCUMENTATION UPDATE PENDING.

```
user_mappings:
    "discord_username1234":
        fluxer_username: "fluxer_EdgyZZ#1211"
        fluxer_auth_key: "fluxer_user-EdgyZZ.token"
```

## Storing Credentials and IDs

Configuration is done through the `config.yaml` file in the project directory.

Stored credential files should have the `.token` extension.

## Configuration YAML File 

This program reads a `config.yaml` file, in its root program directory. This is a template example:

    discord:
      token_file: "discord_token.token"
      guild_id: "YOUR_DISCORD_SERVER_ID"
    Fluxer:
      token_file: "Fluxer_token.token"
      server_id: "YOUR_FLUXER_SERVER_ID"
    delays:
      between_messages_seconds: 0.5
      between_channels_seconds: 5.0

    user_mappings:
      discord:
        "STABLE_ID":
          fluxer_username: "EXPORT_TARGET_USERNAME"
          fluxer_auth_key_file: "./dist/fluxer_user-my_name.token"
        "STABLE_ID":
          fluxer_bot: true
          fluxer_username: "MyBot#1234"

### Example Configuration YAML File with Masquerading

For the bot itself:
```
"147347117134754":
  fluxer_bot: true
```
Do not provide a Fluxer user authentication credential in the latter case.

```
archive:
  path: "./dist/archive"

# --- Discord source configuration ---
discord:
  # Use either token or token_file, not both.
  token_file: "./dist/discord_bot.token"
  guild_id: "1514424954310920479"

# --- Fluxer destination configuration ---
fluxer:
  token_file: "./dist/fluxer_export-bot.token"
  server_id: "1459964012871908"

# --- Migration delays ---
delays:
  between_messages_seconds: 0.5
  between_channels_seconds: 2.5

user_mappings:
  discord:
    "132866533258784":
      fluxer_username: "Lee#0153"
      fluxer_auth_key_file: "./dist/fluxer_user-lee.token"
    "147347117134754":
      fluxer_bot: true
      fluxer_username: "MyBot#1586"
#      fluxer_auth_key_file: "./dist/fluxer_user-bot.token"
```

---
      
## Automatically Install: Run the Setup.sh Script

To automatically install the program, open a command terminal at the location where you have `Arc-Sync-Engine` code files. Run:

    sh setup.sh
  
This will create a virtual python environment and install the program's dependency files.

## Verify Program is Available -- Display the Help Output

Finally, you are ready. To run the exporter, open a command terminal at the location where you have `Arc-Sync-Engine` code files. Run:

    source .venv/bin/python
    archive-sync-engine -h

# Usage / Using the program: Documentation Guide & Help Info for Commands

To see a top level summary of options, run:

    archive-sync-engine -h

To see more specific info about a command, use the format `archive-sync-engine SELECTED_OPTION -h`. Examples:

    archive-sync-engine init -h
    archive-sync-engine import -h

# Importing to an Archive

## Create Configuration for an Archive (1st Step)

Nearly all options can be configured into a YAML file (such as `config.yaml`).

### Config Example Output Save

To get an example of a configuration file, run command:

    archive-sync-engine config-example --output ./config.yaml

This would create a generic template output of the config.yaml file, which the user must edit.

Rule when defining usernames:
> “For this Discord user, which Fluxer identity should represent them when the Archive is exported to Fluxer?”

Example section:

    user_mappings:
      discord:
        "123456789012345678":
          fluxer_username: "BobsFluxerAccount#0909"
          fluxer_auth_key_file: "bob_fluxer_auth.key"
          # Optional source-side Discord credential for this user, if applicable.
          # discord_auth_key_file: "./dist/discord_user-Bob.key"

## Initialize an Archive (2nd Step)

Assuming your config-yaml file is locally stored and named `config.yaml`.

    archive-sync-engine init --config ./config.yaml

Do not skip this step.

The architecture deliberately does not have `import` silently initialize an Archive, because an incorrect Archive path should not accidentally cause data to be written somewhere unintended.

## Import to Archive (3rd Step)

    archive-sync-engine import --config ./config.yaml

The final output of a successful import action should be a folder (as defined either by the configuration file or by input commands) containing a mirror of the input-source.

## Update/Refresh the Import to Archive (4th Step)

To refresh the archive (gathering latest updates from input-source), run `import` command again with the `--resume` option:

    archive-sync-engine import --config ./config.yaml --resume

This should update the stored archive contents, mirroring of the input-source.

This limited time window only applies to currently known (stored in the Archive), content. A newly discovered conversation, or one for which no cursor exists, can cause a full message traversal for that conversation.

Likewise, an interrupted import being resumed is a different case: that uses the durable checkpoint rather than the completed-run incremental-refresh mechanism. The handoff explicitly distinguishes interrupted recovery from completed-run refresh.


# Syncing Between Origin -> Archive -> Target

A completed import followed by `--resume` is still treated as an incremental refresh, and the Discord adapter's 7-day lookback remains applicable there.

WARNING: This has not been tested.
NOTE: The `--resume` option limits scanning from the origin-server over the time range of 7-day window. This can be configured with the `--lookback-days` switch.

    archive-sync-engine sync --config ./config.yaml
    archive-sync-engine sync --config ./config.yaml --resume
    archive-sync-engine sync --config ./config.yaml --lookback-days 30

The `--lookback-days` value is expressed in days and can be fractional. For example, `--lookback-days 2.5` means 60 hours.

This limited time window only applies to currently known (stored in the Archive), content. A newly discovered conversation, or one for which no cursor exists, can cause a full message traversal for that conversation.

Likewise, an interrupted import being resumed is a different case: that uses the durable checkpoint rather than the completed-run incremental-refresh mechanism. The handoff explicitly distinguishes interrupted recovery from completed-run refresh.

## How to Interrupt

Pressing `CTRL+C` on the keyboard will halt the program, and it can be resumed later. The archiving process is ATOMIC-compatible, meaning that it will write the last safe data before attempting a new operation.

Simply run:

    archive-sync-engine import --config ./config.yaml --resume

# Exporting to a Server

    archive-sync-engine export --config ./config.yaml

### A few things to be aware of

- GOOD NEWS: The Archive commits data to itself every time it does the smallest unit of action (importing or exporting).
- NOTE: Because the Archive performs full source reconciliation, rather than a source-specific incremental cursor, issuing the `import` command again with the `--resume` option will check the ***entire*** input-source again.
  - To limit the `import` step, use the `--lookback-days` option, and specify the number of days (fractional values are allowed, such as 2.5).

# Tags and Named Checkpoints

The Archive format includes a source control Git-like tag naming system.

It provides:

- Human-readable immutable tags such as:
    - `Discord Export v1, 2026-10-13`
    - `Discord Export v2, 2026-12-01`
- Monotonically ordered tag sequences.
- Lookup by tag name or opaque tag ID.
- Tag ranges between two named checkpoints.
- A SHA-256 fingerprint of `archive.sqlite` at tag creation, allowing future tooling to determine that the underlying Archive storage changed.
- Source-import metadata captured with the tag:
    - source adapter (`discord`, `fluxer`, etc.)
    - source scope
    - import session ID
    - import status
    - import start/update time
    - importer checkpoint
- failure information, when applicable.

Example:

    archive-sync-engine tag create --archive /path/to/archive --name "Discord Export v1, 2026-10-13"
    archive-sync-engine tag list --archive /path/to/archive
    archive-sync-engine tag show --archive /path/to/archive "Discord Export v1, 2026-10-13"
    archive-sync-engine tag range --archive /path/to/archive \
        --start "Discord Export v1, 2026-10-13" \
        --end "Discord Export v2, 2026-12-01"

`range` can also use `--inclusive`.

## Uses of Tagging

The tagging system is currently only for manual marking of records. This feature is important since later other operations may be desired over the Archive data (possibly with outside tooling).

The dev-team's use-case for this feature is in the future it may become necessary to want to edit previously stored Archive messages (such as redacting, scrubbing, or substituting contents). This tagging system provides useful date and checkpoint record creation.

#### Emojis

The program will migrate custom emoji from an origin-server to target-servers. 

If the emoji of the same name already exists on the target server, it will skip uploading. (In order to avoid duplication.) It does not check the image contents, only the emoji name. So for example, if migrating 'kek' from Discord, but 'kek' already exists on Fluxer, this emoji will be skipped.

---

# FEATURE STATUS for Migration

## Channel Creation
- Initial migration: 
- Updated changes migrated after initial migration:
  - Create new channel when ran after update: 
  - Delete new channel when ran after update: 


## Messages to Channels & Message Attachment

### Maximum Message Length Handling

It is possible to overrun the maximum message length when exporting a non-masqueraded message. Scenario: when export-bot will attempt to prepend a username to the delivered message.

Example:
    (sent by username Spritz) `That's a good thought` would become `Spritz: that's a good thought`

FIXME: This edge-case needs to be handled.

# Not Supported Features

Threads or Threading of conversations: Not supported yet, but the feature is PENDING Python library support.

Fluxer Servers now support conversatoin Threads, but the Fluxer.Py library has not released the updated support for the Threads feature yet. (It is currently in work.) When it is released, Arc-Sync-Engine will update to support this feature also.

## Future Workarounds

During the migration process, dedicated suffixed `-thread` channels could be created.

# Future Roadmap / Pending Tasks

## Threads

- Pinned threads within channels
- Pinned messages within a thread
- Implement and verify Thread preservation

# Testing / Unit Tests

Run the following:

    python -m pytest archive_sync_engine

There are many warnings from the Discord sub-libraries, which is why we suppress them.

# Version Support

Tested with Python 3.11, but in theory should work for versions 3.10.

# Legacy Documentation

This project was forked from [discord-to-fluxer](https://github.com/cdobrich/discord-to-fluxer), and rewritten from scratch to be robust and support the necessary complexity of the operations.
