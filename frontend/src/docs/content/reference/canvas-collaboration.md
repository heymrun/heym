# Canvas Collaboration

Everyone who opens the same workflow sees the others on the canvas and works on one shared draft. Edits show up for everyone as they happen, each person's pointer moves in their own color, you can follow what someone else is looking at, and you can talk with the microphone.

## Who is on the canvas

The avatars at the top left of the canvas show everyone who has the workflow open, including you. Each person has a color: their avatar ring, their pointer and the frame you see while following them all use it. Hover an avatar to see the name and whether that person can edit or only view. More than five people show as **+N**.

## Editing together

People with edit access change the same draft. Adding, deleting, moving and connecting nodes, and changing node settings, reach every open canvas within a moment, without saving first.

- **Saving.** Anyone with edit access can save. The save stores the shared draft, and **Unsaved changes** clears for everyone whose canvas matches what was saved.
- **Same setting, same moment.** When two people change the same node's settings at the same time, the change that reaches the server last wins on every screen. Moving a node and editing its settings never overwrite each other.
- **Name and description.** While someone renames the workflow or edits its description, everyone sees the text as it is typed, underlined in their color. **Enter** keeps it for everyone, **Esc** puts the old text back.
- **Undo.** **Ctrl+Z** undoes only your own changes. Changes made by others stay.
- **Joining later.** If someone already has unsaved changes, a canvas that opens the workflow later starts from that draft, not from the last save.
- **View-only access.** People who can only view see every change live but cannot edit. If the last person with edit access leaves without saving, the unsaved changes are discarded and view-only canvases return to the saved version.
- **Saved elsewhere.** When the workflow is saved outside the canvas (from the Chat tab, over MCP, or by restoring a version in [Edit History](./edit-history.md)), canvases without unsaved changes load the new version. With unsaved changes, editors choose between loading the saved version for everyone and keeping the draft.

## Pointers

Each person's pointer appears with their avatar and name. On the canvas it sits over the same node they point at, whatever your zoom. Over the header, the side panels, the Debug panel, the AI Assistant and open dialogs it lines up with the same control on your screen, even when your window is a different size.

While you follow someone, each of their clicks shows as a short ripple at their pointer, so you can see what they pressed. Other people's pointers stay plain.

If a pointer is over a panel or dialog you do not have open, you do not see it.

## Following someone

Click someone's avatar to follow them. They see a notice that you are following. Your canvas then shows:

- the part of the canvas they look at, and where they point, including over panels and dialogs
- the node list, the node they select, the properties panel and its tab
- what they type into the Run inputs
- the expression dialog, History, Edit History, Share, Portal, cURL and Share as template dialogs they open
- the Workflow Analyzer and the Page Guide
- the Debug panel, a run they start live on your canvas, and the result of their last run
- their AI Assistant: the panel, Agent or Ask, what they are typing, their messages and the answers, read-only

What they click, type, hover and scroll in dialogs, side panels, dropdowns and the AI Assistant happens in your copy too: fields fill in, tabs and options change, menus and hover details open, lists scroll to the same place. Keys they press in a dialog, such as **Esc** to clear the History search, do the same in yours. A tooltip they are reading appears next to their pointer, and a node they point at shows its **Run** and **AI** buttons. Their pointer sits on the same button or row in your copy, even when your screen is a different size. Dialogs, runs and History open on your screen with your own access, so you see what your share allows. A frame in their color around the whole editor marks that you are following.

While you follow, you only watch. Your editor saves, runs and sends nothing, so a button they press, such as **Add** in Share, changes things once, as them, not again as you.

To stop, press **Esc**, click or type anywhere yourself, move the canvas, or click their avatar again.

## Talking

Click the microphone next to the avatars to talk with everyone on the canvas. The first time, the browser asks for microphone access. Browsers allow the microphone only when Heym is opened over `https` or on `localhost`. Opened by a network address such as `http://192.168.0.10:4017`, everything else works but the microphone stays off. You can hear others without turning on your own microphone. The ring of whoever is talking pulses.

Audio goes directly between browsers. It works on the same network, over a VPN, and across most home and office networks. If two people cannot connect, a red dot appears on the avatar. If the browser holds back sound until you interact with the page, an **Enable audio** button appears.

For administrators: to find a direct route, browsers contact the public STUN servers `stun.cloudflare.com` and `stun.l.google.com`. Audio never passes through them or through Heym. Without internet access, people on the same network or VPN still connect.

## Where it works

Pointers, following and talking are available in the desktop editor. The mobile editor receives live edits.

If the editor cannot reach the collaboration connection, for example behind a proxy that does not pass WebSockets, it opens as usual and says once that live collaboration is off. It keeps trying quietly and turns collaboration on when the connection comes back.

See also [Canvas Features](./canvas-features.md), [Edit History](./edit-history.md), and [Keyboard Shortcuts](./keyboard-shortcuts.md).
