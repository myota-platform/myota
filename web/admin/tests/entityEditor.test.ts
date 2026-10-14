import assert from 'node:assert/strict';
import { test } from 'node:test';
import { dirtyEditorSections, type EntityEditorState } from '../src/lib/entityEditor.ts';

const saved: EntityEditorState = {
  name: 'Parque', website: '', description: '', nameNote: '', categories: ['PARK', 'GARDEN'],
  geometry: '{"type":"Point","coordinates":[-5.99,37.39]}', geometryType: 'Point',
  geometryNote: '', location: '[{"country":"Spain"},[]]',
};

test('unchanged and reformatted geometry drafts are clean', () => {
  const draft = { ...saved, geometry: JSON.stringify(JSON.parse(saved.geometry), null, 2) };
  assert.deepEqual(dirtyEditorSections(saved, draft), []);
});
test('all editable sections independently protect unsaved drafts', () => {
  assert.deepEqual(dirtyEditorSections(saved, {
    ...saved, name: 'New name', categories: ['GARDEN', 'PARK'],
    geometryType: 'Polygon', location: 'changed',
  }), ['Name', 'Categories', 'Geometry', 'Location']);
});
test('notes and invalid JSON trigger discard protection', () => {
  assert.deepEqual(dirtyEditorSections(saved, { ...saved, nameNote: 'Evidence', geometry: '{' }),
    ['Name', 'Geometry']);
  assert.deepEqual(dirtyEditorSections(saved, { ...saved, geometryNote: 'Correction' }), ['Geometry']);
});
test('saving one section does not clear another unsaved section', () => {
  const draft = { ...saved, name: 'New name', location: 'manual edit' };
  assert.deepEqual(dirtyEditorSections({ ...saved, name: draft.name }, draft), ['Location']);
});

test('website and description drafts are protected and independently tracked', () => {
  assert.deepEqual(dirtyEditorSections(saved, { ...saved, website: 'https://example.org', description: 'A short description' }), ['Website / description']);
});
