# assets/gamemodes

One image per gamemode card in the intermission menu, named `<gamemode slug>.png`.

No list here on purpose: `nav_images.expected_paths()` derives it from `GAMEMODES`, so the
Image Manager's **Gamemode Cards** section already shows a card per mode that needs one —
including Challenge, which has a card in the menu because that is how the macro reaches it.
A hand-written list here would only go stale the next time a mode is added.
