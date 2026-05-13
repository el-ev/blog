let verified = false;

form.cond('dirty', () => !verified);
form.cond('correct', () => form.get('answer').trim() !== '2147483647');

form.action('verify', () => {
  verified = true;
  form.refresh();
});

form.on('answer', () => {
  verified = false;
  form.refresh();
});

form.cond('summary', () => form.get('item_1') === 'true' || form.get('item_2') === 'true');

form.cond('color-picked', () => form.get('color') !== '');
form.cond('color-red', () => form.get('color') === 'red');
form.cond('color-green', () => form.get('color') === 'green');
form.cond('color-blue', () => form.get('color') === 'blue');
