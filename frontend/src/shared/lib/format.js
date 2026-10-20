export const won = (amount) => `${new Intl.NumberFormat('ko-KR').format(amount)}원`;

export function formatTime(value) {
  return new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
