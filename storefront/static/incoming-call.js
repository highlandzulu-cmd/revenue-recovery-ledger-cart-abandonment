/**
 * Shared "incoming call" UI controller - drives the _incoming_call.html
 * partial wherever it's included (checkout.html, phone.html).
 *
 * Synced across browser tabs via BroadcastChannel: a call triggered on one
 * page (checkout.html, from a real cart-abandonment decision) rings on every
 * other same-origin tab that has this loaded too - e.g. a standalone /phone
 * tab opened next to it for a demo recording. No server round trip, no
 * polling - same-origin tabs just talk to each other directly.
 */
(function () {
    const overlay = document.getElementById("incoming-call-overlay");
    if (!overlay) return; // partial isn't on this page

    const channel = "BroadcastChannel" in window ? new BroadcastChannel("recovery-agent-calls") : null;

    const callScreen = document.querySelector(".phone-screen");
    const messageScreen = document.getElementById("phone-message-screen");
    const messageText = document.getElementById("call-message-text");
    const messageLink = document.getElementById("call-message-link");
    const messageDoneBtn = document.getElementById("message-done-btn");

    const avatar = document.getElementById("ios-call-avatar");
    const subEl = document.getElementById("ios-call-sub");
    const timerEl = document.getElementById("ios-call-timer");
    const acceptBtn = document.getElementById("ios-call-accept");
    const declineBtn = document.getElementById("ios-call-decline");
    const endBtn = document.getElementById("ios-call-end");
    const endGroup = document.getElementById("ios-call-end-group");
    const audio = document.getElementById("ios-call-audio");
    const clockEl = document.getElementById("ios-clock");
    let timerInterval = null;
    // Set by triggerIncomingCall/the broadcast listener - what to text after
    // the call, if anything. No payload (e.g. the plain preview button) means
    // no follow-up message, same as there being nothing to actually send.
    let currentPayload = null;

    function updateClock() {
        const now = new Date();
        const h = now.getHours() % 12 || 12;
        const m = String(now.getMinutes()).padStart(2, "0");
        clockEl.textContent = h + ":" + m;
    }
    updateClock();
    setInterval(updateClock, 30000);

    function showIncomingCall() {
        callScreen.hidden = false;
        messageScreen.hidden = true;
        avatar.classList.add("ringing");
        subEl.textContent = "mobile";
        subEl.hidden = false;
        timerEl.hidden = true;
        timerEl.textContent = "00:00";
        acceptBtn.parentElement.hidden = false;
        declineBtn.parentElement.hidden = false;
        endGroup.hidden = true;
        overlay.hidden = false;
    }

    // A text follows a real answered-and-ended call with something to say -
    // not a decline (you never spoke), not a preview trigger (no real
    // message/link exists for it).
    function showFollowUpMessage() {
        if (!currentPayload || !currentPayload.customerMessage) return false;
        messageText.textContent = currentPayload.customerMessage;
        if (currentPayload.razorpayLink) {
            messageLink.href = currentPayload.razorpayLink;
            messageLink.textContent = currentPayload.razorpayLink;
            messageLink.hidden = false;
        } else {
            messageLink.hidden = true;
        }
        callScreen.hidden = true;
        messageScreen.hidden = false;
        overlay.hidden = false;
        return true;
    }

    function endCall(withMessage) {
        audio.pause();
        audio.currentTime = 0;
        if (timerInterval) clearInterval(timerInterval);
        if (withMessage && showFollowUpMessage()) return; // overlay stays open, showing the text
        overlay.hidden = true;
    }

    acceptBtn.addEventListener("click", () => {
        avatar.classList.remove("ringing");
        subEl.hidden = true;
        acceptBtn.parentElement.hidden = true;
        declineBtn.parentElement.hidden = true;
        endGroup.hidden = false;
        timerEl.hidden = false;

        let seconds = 0;
        timerInterval = setInterval(() => {
            seconds++;
            const m = String(Math.floor(seconds / 60)).padStart(2, "0");
            const s = String(seconds % 60).padStart(2, "0");
            timerEl.textContent = m + ":" + s;
        }, 1000);

        audio.currentTime = 0;
        audio.play().catch(() => { /* no recording yet - call just stays quiet, same as a bad line */ });
        audio.onended = () => setTimeout(() => endCall(true), 1200);
    });

    declineBtn.addEventListener("click", () => endCall(false));
    endBtn.addEventListener("click", () => endCall(true));
    messageDoneBtn.addEventListener("click", () => { overlay.hidden = true; });

    // Public API: rings this tab AND every other same-origin tab that has
    // this script loaded (via BroadcastChannel - includes itself only if it
    // also listens below, which it does, so calling this here is enough).
    // payload is optional: { customerMessage, razorpayLink }.
    window.triggerIncomingCall = function (payload) {
        currentPayload = payload || null;
        showIncomingCall();
        if (channel) channel.postMessage({ type: "incoming_call", payload: currentPayload });
    };

    // For a real dispatch that isn't a voice call (send_reminder_* -> a
    // WhatsApp-style text, not a phone ringing) - jumps straight to the
    // message screen, no ringing/accept step, since nothing actually rang.
    window.triggerIncomingMessage = function (payload) {
        currentPayload = payload || null;
        showFollowUpMessage();
        if (channel) channel.postMessage({ type: "incoming_message", payload: currentPayload });
    };

    if (channel) {
        channel.onmessage = (event) => {
            if (!event.data) return;
            if (event.data.type === "incoming_call") {
                currentPayload = event.data.payload || null;
                showIncomingCall();
            } else if (event.data.type === "incoming_message") {
                currentPayload = event.data.payload || null;
                showFollowUpMessage();
            }
        };
    }

    const previewBtn = document.getElementById("preview-call-btn");
    if (previewBtn) previewBtn.addEventListener("click", () => window.triggerIncomingCall());
})();
