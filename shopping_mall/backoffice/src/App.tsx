import { Outlet } from 'react-router-dom';
import Sidebar from '@/components/layout/Sidebar';
import TopBar from '@/components/layout/TopBar';

export default function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <Sidebar />
      <div className="ml-60">
        <TopBar />
        <main className="min-h-[calc(100vh-3.5rem)]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
