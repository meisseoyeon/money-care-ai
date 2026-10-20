import { createMockApi } from '../mocks/mockApi.js';
import { createHttpApi } from './httpApi.js';

export const api = import.meta.env.VITE_API_MODE !== 'mock'
  ? createHttpApi(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  : createMockApi({ storage: window.localStorage, sessionStorage: window.sessionStorage });
