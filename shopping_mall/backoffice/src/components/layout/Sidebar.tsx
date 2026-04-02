import { NavLink } from 'react-router-dom';

const navItems = [
  { to: '/', label: '대시보드', icon: '📊' },
  { to: '/chatbot', label: '챗봇 관리', icon: '🤖' },
  { to: '/calendar', label: '판매 캘린더', icon: '📅' },
  { to: '/shipments', label: '배송 관리', icon: '🚚' },
  { to: '/reports', label: '리포트', icon: '📋' },
  { to: '/analytics', label: '분석', icon: '📈' },
  { to: '/expenses', label: '비용 관리', icon: '💰' },
];

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-60 bg-gray-900 text-white flex flex-col z-50">
      <div className="px-5 py-6 border-b border-gray-700">
        <h1 className="text-lg font-bold tracking-tight">FarmOS 백오피스</h1>
      </div>
      <nav className="flex-1 py-4 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-3 text-sm transition-colors ${
                isActive
                  ? 'bg-gray-700 border-l-4 border-[#03C75A] text-white font-semibold'
                  : 'border-l-4 border-transparent text-gray-300 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-4 border-t border-gray-700 text-xs text-gray-500">
        FarmOS Admin v1.0
      </div>
    </aside>
  );
}
