import { createBrowserRouter } from 'react-router-dom';
import App from '@/App';
import DashboardPage from '@/pages/DashboardPage';
import ChatbotPage from '@/pages/ChatbotPage';
import CalendarPage from '@/pages/CalendarPage';
import ShipmentsPage from '@/pages/ShipmentsPage';
import ReportsPage from '@/pages/ReportsPage';
import AnalyticsPage from '@/pages/AnalyticsPage';
import ExpensesPage from '@/pages/ExpensesPage';

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'chatbot', element: <ChatbotPage /> },
      { path: 'calendar', element: <CalendarPage /> },
      { path: 'shipments', element: <ShipmentsPage /> },
      { path: 'reports', element: <ReportsPage /> },
      { path: 'analytics', element: <AnalyticsPage /> },
      { path: 'expenses', element: <ExpensesPage /> },
    ],
  },
]);

export default router;
