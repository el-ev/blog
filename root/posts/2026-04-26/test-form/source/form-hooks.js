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
