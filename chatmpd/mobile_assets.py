"""Embedded static assets for the ChatMPD mobile client."""

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" content="#111318">
  <title>ChatMPD</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <header><strong>ChatMPD</strong><span id="connection">Local PC</span></header>
  <main>
    <section id="pairing" class="card">
      <h1>Pair with ChatMPD</h1>
      <p>Enter the one-time code shown by ChatMPD on your PC.</p>
      <label>Device name<input id="device-name" maxlength="80" value="My phone"></label>
      <label>Pairing code<input id="pairing-code" inputmode="numeric" maxlength="8" autocomplete="one-time-code"></label>
      <button id="pair-button">Pair device</button>
      <p id="pair-message" class="message"></p>
    </section>
"""
