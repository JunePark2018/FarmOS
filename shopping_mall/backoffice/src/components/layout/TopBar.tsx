export default function TopBar() {
  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 sticky top-0 z-40">
      <div />
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">관리자</span>
        <div className="w-8 h-8 rounded-full bg-[#03C75A] text-white flex items-center justify-center text-sm font-bold">
          A
        </div>
      </div>
    </header>
  );
}
