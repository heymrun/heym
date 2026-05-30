# Chat Voice (TTS & STT)

The Chat tab can read messages aloud and run a hands-free interactive voice mode, powered by [ElevenLabs](https://elevenlabs.io). Both directions use one ElevenLabs credential: **text-to-speech** for playback and **Scribe speech-to-text** for the microphone.

## Setup

1. Open **User Settings** (your name, top right) → **Voice** tab.
2. Pick an **ElevenLabs credential**, or click **Add credential** to create one. The API key needs the **Text to Speech**, **Speech to Text**, and **Voices** permissions enabled in your ElevenLabs account.
3. Choose a **Voice** from your ElevenLabs account.
4. Click **Save Voice Settings**.

If you press a voice button before setting this up, the Voice tab opens automatically so you can finish configuring.

The ElevenLabs API key is stored encrypted and never reaches the browser — all calls are proxied through the Heym backend. See [Credentials](./credentials.md) and [User Settings](./user-settings.md).

## Read a message aloud

Every message bubble (yours and the assistant's) has a speaker button next to **Copy**. Click it to play the message; click again — or play another message — to stop. Playback uses the ElevenLabs multilingual model, so the language of the text is detected automatically.

## Interactive voice mode

The waveform button in the chat input opens a full-screen, hands-free voice mode (light/dark and mobile aware):

1. It listens through your microphone and detects when you stop speaking.
2. Your speech is transcribed with **Scribe** (language auto-detected — no manual TR/EN toggle).
3. The transcript is sent as a normal chat message in the **same conversation**.
4. The assistant's reply is read back aloud, then it resumes listening.

Use the **mute** button to pause listening and the **✕** to exit (which releases the microphone). Recording works in all modern browsers, including Firefox.

## Notes

- Voice and credential selection are per-user preferences; the active conversation, model, and credential for the LLM are unchanged.
- ElevenLabs usage (both TTS and STT) is billed to your own ElevenLabs account.

## Related

- [Chat Tab](../tabs/chat-tab.md) – Dashboard chat where voice lives
- [Credentials](./credentials.md) – How API keys are stored and referenced
- [User Settings](./user-settings.md) – Where the Voice tab lives
