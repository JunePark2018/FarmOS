import { format } from 'date-fns';
import { ko } from 'date-fns/locale';

export function formatPrice(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDate(date: string | Date, pattern = 'yyyy-MM-dd HH:mm'): string {
  return format(new Date(date), pattern, { locale: ko });
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + '...';
}
