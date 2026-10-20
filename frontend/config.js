const isLocalFrontend =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1";

window.IMPROBUDDY_API_BASE =
  window.IMPROBUDDY_API_BASE ||
  (isLocalFrontend
    ? "http://127.0.0.1:8000"
    : "https://englishbuddy-gsgg.onrender.com");
