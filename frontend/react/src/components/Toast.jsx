import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

export function Toast() {
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState("neutral");
  const [visible, setVisible] = useState(false);
  const toastTimerRef = useRef(null);

  useEffect(() => {
    const handleToast = (event) => {
      const nextMessage = String(event.detail?.message || "");
      if (!nextMessage) return;
      window.clearTimeout(toastTimerRef.current);
      setMessage(nextMessage);
      setTone(event.detail?.tone || event.detail?.type || "neutral");
      setVisible(true);
      toastTimerRef.current = window.setTimeout(() => setVisible(false), event.detail?.duration || 2400);
    };
    window.addEventListener("knowflow:react-toast", handleToast);
    return () => {
      window.removeEventListener("knowflow:react-toast", handleToast);
      window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  const normalizedTone = ["error", "success", "warning", "neutral"].includes(tone)
    ? tone
    : "neutral";
  const baseClassName = normalizedTone === "error"
    ? "toast error"
    : `toast ${normalizedTone}`;
  const className = visible ? `${baseClassName} show` : baseClassName;

  const dismiss = () => {
    window.clearTimeout(toastTimerRef.current);
    setVisible(false);
  };

  return (
    <div className={className} id={"toast"} data-tone={normalizedTone} role={normalizedTone === "error" ? "alert" : "status"} aria-live={normalizedTone === "error" ? "assertive" : "polite"} aria-atomic={"true"}>
      <span className={"toast-message"}>{message}</span>
      <button className={"toast-dismiss"} type={"button"} aria-label={"关闭提示"} onClick={dismiss}>
        <X size={15} strokeWidth={2} aria-hidden={"true"} />
      </button>
    </div>
  );
}
