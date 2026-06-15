export function LoadingState() {
  return (
    <div className="flex h-dvh items-center justify-center bg-white"
         role="status" aria-live="polite">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#0066cc]/20 border-t-[#0066cc]/60" />
    </div>
  );
}
