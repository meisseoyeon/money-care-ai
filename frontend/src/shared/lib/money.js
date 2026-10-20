import { AppError } from './errors.js';

export function validateMoney(value, { allowZero = false } = {}) {
  if (!Number.isSafeInteger(value) || value < (allowZero ? 0 : 1) || value > 1000000000) {
    throw new AppError(allowZero ? '금액은 0원 이상 10억 원 이하의 정수로 입력해 주세요.' : '금액은 1원 이상 10억 원 이하의 정수로 입력해 주세요.');
  }
  return value;
}
