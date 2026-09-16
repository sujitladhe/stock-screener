// soundAlert.js — plays a short, attention-getting beep sequence using
// the Web Audio API directly, rather than bundling an external audio
// file. Browsers require a user gesture before audio can play in most
// cases -- the first click/keypress anywhere on the page after load
// satisfies this, so as long as the user has interacted with the page
// at all (extremely likely, they had to log in), this works without
// needing a separate "enable sound" button.

let audioContext = null;

function getAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  return audioContext;
}

/**
 * Plays a short two-beep alert sound. Each beep is a simple sine tone;
 * two short beeps rather than one long tone reads as more "alert-like"
 * and less like an error buzzer.
 */
export function playAlertSound() {
  try {
    const ctx = getAudioContext();
    const now = ctx.currentTime;

    playBeep(ctx, now, 880, 0.15);
    playBeep(ctx, now + 0.2, 880, 0.15);
  } catch (err) {
    console.error("Could not play alert sound:", err);
  }
}

function playBeep(ctx, startTime, frequency, duration) {
  const oscillator = ctx.createOscillator();
  const gainNode = ctx.createGain();

  oscillator.type = "sine";
  oscillator.frequency.value = frequency;

  gainNode.gain.setValueAtTime(0, startTime);
  gainNode.gain.linearRampToValueAtTime(0.3, startTime + 0.01);
  gainNode.gain.linearRampToValueAtTime(0, startTime + duration);

  oscillator.connect(gainNode);
  gainNode.connect(ctx.destination);

  oscillator.start(startTime);
  oscillator.stop(startTime + duration);
}
