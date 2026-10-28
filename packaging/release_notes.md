Zhia Lian Quest Browser {version}, built and tested by GitHub on each system (commit {commit}, branch {branch}).

## Which file?

| Your computer | Download |
| --- | --- |
| Mac with Apple Silicon (Apple menu → About This Mac says "Chip: Apple M…") | `ZhiaLianQuestBrowser-{version}-mac-apple-silicon.zip` |
| Mac with an Intel processor ("Processor: … Intel …") | `ZhiaLianQuestBrowser-{version}-mac-intel.zip` |
| Windows | `ZhiaLianQuestBrowser{version}.exe` |

## The first time on a Mac

1. Double-click the zip to unzip it, then double-click **ZhiaLianQuestBrowser**. It opens in a Terminal window.
2. macOS blocks it the first time, because it isn't signed with a paid Apple developer account. Open **System Settings → Privacy & Security**, scroll down to the message about ZhiaLianQuestBrowser, click **Open Anyway** and confirm. (Or in Terminal: `xattr -d com.apple.quarantine ~/Downloads/ZhiaLianQuestBrowser`.)
3. If macOS asks whether it may accept incoming network connections, choose **Allow** to use it from your phone or other computers, or **Deny** to use it on this Mac only.

After that it starts with a double-click, and your browser opens the app. To quit, close the Terminal window or press Ctrl+C. To use options such as `--port:8080` or `--localhostonly`, start it from Terminal: `./ZhiaLianQuestBrowser --port:8080`.

When you import a player file, macOS may ask once whether Terminal can see your Documents folder, because the app looks for Project Gorgon's files there too.

## The first time on Windows

Windows may say "Windows protected your PC". Choose **More info**, then **Run anyway**.
