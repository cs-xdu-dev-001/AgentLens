export function KnowFlowLogo({ className = "" }) {
  return (
    <svg className={["knowflow-logo", className].filter(Boolean).join(" ")} viewBox={"0 0 48 48"} aria-hidden={"true"} focusable={"false"}>
      <rect className={"knowflow-logo-frame"} x={"4"} y={"4"} width={"40"} height={"40"} rx={"12"} />
      <circle className={"knowflow-logo-lens"} cx={"21"} cy={"21"} r={"10.5"} />
      <path className={"knowflow-logo-lens"} d={"m28.4 28.4 7.4 7.4"} />
      <path className={"knowflow-logo-flow"} d={"m21 21-4.8-4.2M21 21l5-4.1M21 21l3.8 5"} />
      <circle className={"knowflow-logo-node"} cx={"16.2"} cy={"16.8"} r={"2"} />
      <circle className={"knowflow-logo-node"} cx={"26"} cy={"16.9"} r={"2"} />
      <circle className={"knowflow-logo-node"} cx={"24.8"} cy={"26"} r={"2"} />
      <circle className={"knowflow-logo-core"} cx={"21"} cy={"21"} r={"2.2"} />
    </svg>
  );
}
