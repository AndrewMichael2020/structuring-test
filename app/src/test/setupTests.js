import '@testing-library/jest-dom';
import React from 'react';
global.React = React;

import { TextEncoder, TextDecoder } from 'util';
// Polyfill for packages requiring TextEncoder/TextDecoder in Node test env
if (!global.TextEncoder) {
	global.TextEncoder = TextEncoder;
}
if (!global.TextDecoder) {
	global.TextDecoder = TextDecoder;
}

// Provide a default fetch mock to prevent tests from failing due to network
if (!global.fetch) {
	global.fetch = jest.fn(async (url) => {
		if (typeof url === 'string' && url.includes('/api/reports/list')) {
			return { ok: true, json: async () => [] };
		}
		return { ok: true, json: async () => ({}) };
	});
}
