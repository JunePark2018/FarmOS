import { format } from 'date-fns';
import { ko } from 'date-fns/locale';

export function formatPrice(price: number | null | undefined): string {
  if (price == null || isNaN(price)) return '₩0';
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(price);
}

export function getDiscountedPrice(price: number, discountRate: number): number {
  return Math.floor(price * (1 - discountRate / 100));
}

export function formatDate(date: string | Date | null | undefined, pattern = 'yyyy-MM-dd HH:mm'): string {
  if (!date) return '-';
  try {
    const parsed = new Date(date);
    if (isNaN(parsed.getTime())) return '-';
    return format(parsed, pattern, { locale: ko });
  } catch {
    return '-';
  }
}

export function truncate(str: string | null | undefined, length: number): string {
  if (!str) return '';
  if (str.length <= length) return str;
  return str.slice(0, length) + '...';
}
