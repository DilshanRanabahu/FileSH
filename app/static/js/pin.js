// PIN screen: for devices that open the address without scanning the QR code.

import { sendJson } from "./api.js";
import { $ } from "./dom.js";
import { hooks } from "./state.js";

export function showPinScreen() {
  $("app").hidden = true;
  $("message").hidden = true;
  $("status").hidden = true;
  $("pin-screen").hidden = false;
  $("pin-input").focus();
}

export function setupPin() {
  $("pin-input").addEventListener("input", (event) => {
    // Show the PIN as "123 456" while typing.
    const digits = event.target.value.replace(/\D/g, "").slice(0, 6);
    event.target.value = digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
    $("pin-error").textContent = "";
  });
  $("pin-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const pin = $("pin-input").value.replace(/\D/g, "");
    if (pin.length !== 6) {
      $("pin-error").textContent = "Enter all 6 digits.";
      return;
    }
    try {
      await sendJson("/api/pin", "POST", { pin });
    } catch (error) {
      $("pin-error").textContent = error.message;
      $("pin-input").select();
      return;
    }
    $("pin-input").value = "";
    $("pin-screen").hidden = true;
    hooks.refreshStatus();
  });
}
