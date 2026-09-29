"use client";

export function IdleWarningModal({
  secondsRemaining,
  onStayActive,
  onLogout,
}: {
  secondsRemaining: number;
  onStayActive: () => void;
  onLogout: () => void;
}) {
  const minutes = Math.floor(secondsRemaining / 60);
  const seconds = secondsRemaining % 60;
  const clock =
    minutes > 0
      ? `${minutes}m ${String(seconds).padStart(2, "0")}s`
      : `${seconds}s`;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="idle-warning-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <h2 id="idle-warning-title" className="text-xl font-bold mb-2">
          Still there?
        </h2>
        <p className="text-gray-600 mb-4">
          You&apos;ve been inactive. For your privacy you&apos;ll be signed out
          in <strong>{clock}</strong>.
        </p>
        <div className="flex gap-3">
          <button
            onClick={onStayActive}
            autoFocus
            className="flex-1 bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700"
          >
            Stay signed in
          </button>
          <button
            onClick={onLogout}
            className="px-4 py-2 rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Sign out now
          </button>
        </div>
      </div>
    </div>
  );
}
