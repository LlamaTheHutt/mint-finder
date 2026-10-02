# mint-finder

A search window for programs, files, and folders on Linux Mint.


|            |                                                                                   |
| ---------- | --------------------------------------------------------------------------------- |
| Tested on  | Linux Mint 22.3 - Cinnamon 64-bit                                                 |
| License    | GPL-3.0 or later ([COPYING](COPYING))                                             |
| Settings   | GSettings `com.linuxmint.finder`                                                  |
| Local data | `~/.config/mint-finder/` (migrated from `~/.local/share/mint-finder/` if present) |


I made this because I was tired of opening Nemo and going through folders one by one, or waiting for its search. I'm [LlamaTheHutt](https://github.com/LlamaTheHutt). I hope you all enjoy it. Linux Mint is welcome to take this project and implement it.

It follows the layout used by official Mint tools such as [mintwelcome](https://github.com/linuxmint/mintwelcome)
and [mintnanny](https://github.com/linuxmint/mintnanny), and the workflow in the
[Linux Mint Developer Guide](https://linuxmint-developer-guide.readthedocs.io/en/latest/).

## Keyboard


| Key         | Action                                       |
| ----------- | -------------------------------------------- |
| Super+Space | Open Finder (closes it when already focused) |
| Type        | Search                                       |
| Arrow keys  | Move between results                         |
| Enter       | Open the selected result                     |
| Escape      | Close the window                             |


Cinnamon uses Super+Space to switch keyboard layout. Installing Finder moves that job to the keyboard layout key and uses Super+Space for search. Uninstall puts Super+Space back. Preferences can choose another shortcut.

## Preferences

Open Preferences from the button beside the search box. A sidebar switches between General, Bookmarks, and Blacklist.


| Option                    | What it does                                                       |
| ------------------------- | ------------------------------------------------------------------ |
| Shortcut                  | Choose the key that opens Finder                                   |
| Hidden files              | Include hidden files and folders                                   |
| Frequency                 | Show frequently opened results first                               |
| Programs and folders only | Skip file matches                                                  |
| Search folders            | Add or remove folders to search                                    |
| Bookmarks                 | Add, remove, or move a starred file or folder to the blacklist     |
| Blacklist                 | Leave out a folder and everything inside it. Move one to bookmarks |


File and folder results show a star button to add or remove a bookmark, and a stop button to blacklist that folder. On a file, the stop button blacklists the folder the file is in. Matching bookmarks are listed first. Results are drawn from every folder you listed, and scrolling to the bottom loads more matches.

## Search


| Source         | Behavior                                                        |
| -------------- | --------------------------------------------------------------- |
| `plocate`      | Used when installed; also searches the configured folders       |
| Folder walk    | Used without `plocate`; walks the folders listed in Preferences |
| Default folder | Your home folder                                                |
| Nested folders | A folder under another listed folder is searched once           |


Linux Mint does not include `plocate` by default. Folder matching does not spend the walk budget only on files, so folder search stays responsive. A folder on the blacklist, and everything inside it, is left out of the walk, locate results, and bookmarks. Programs are still searched.

## Run from the source tree

On Linux Mint 22.x or LMDE, `./test` uses libraries that are already installed. No extra packages are required to open the window.


| Command            | Effect                                                                                                   |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| `./test`           | Launch the search window from the source tree (nothing copied into `/usr`)                               |
| `./test --install` | Install into `/usr`, register Super+Space, install `plocate` if missing, remove an older login autostart |
| `./uninstall`      | Remove the installed program and the Super+Space shortcut                                                |


Without `plocate`, Finder walks the folders listed in Preferences. Cinnamon runs `mint-finder` when you press the shortcut.

## Tests

```
/usr/bin/python3 -m unittest discover -s tests
```

Use `/usr/bin/python3` so the tests import the system GTK libraries.

## Build a package

Building a `.deb` is separate from running the app.


| Step                              | Command                                                                  |
| --------------------------------- | ------------------------------------------------------------------------ |
| First build (installs build deps) | `sudo apt install mint-dev-tools --install-recommends` then `mint-build` |
| Later builds                      | `dpkg-buildpackage`                                                      |


The changelog distribution is `UNRELEASED`, so this build does not sign the package. The resulting `.deb` files are written to the parent directory.


| Goal                                                 | How                                                                                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Sign `.dsc` / `.buildinfo` / `.changes` during build | Set a real distribution in `debian/changelog`, match the maintainer to a GPG key, run `dpkg-buildpackage` without `-us`/`-uc` |
| Sign after an unsigned build                         | `debsign ../mint-finder_*.changes`                                                                                            |
| Embed a signature in the `.deb`                      | `dpkg-sig --sign builder ../mint-finder_*.deb`                                                                                |




## Project layout


| Path                                             | Role                     |
| ------------------------------------------------ | ------------------------ |
| `usr/bin/mint-finder`                            | Launcher                 |
| `usr/lib/linuxmint/mint-finder/`                 | Application code         |
| `usr/share/applications/mint-finder.desktop`     | Desktop entry            |
| `usr/share/linuxmint/mint-finder/mint-finder.ui` | Glade UI                 |
| `uninstall`                                      | Remove an installed copy |
| `debian/`                                        | Packaging                |




## Coding style

This project follows the Mint
[coding guidelines](https://linuxmint-developer-guide.readthedocs.io/en/latest/guidelines.html).


| Rule      | Detail                                                              |
| --------- | ------------------------------------------------------------------- |
| Indent    | 4 spaces, no tabs                                                   |
| Lines     | No trailing spaces; 120-column limit                                |
| Style     | Prefer simple statements over one-liners and complicated conditions |
| Exception | `debian/rules` keeps the single tab that `make` requires            |


