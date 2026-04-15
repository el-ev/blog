export default {
  multipass: true,
  plugins:
      [
        {
          name: 'preset-default',
          params: {
            overrides: {
              cleanupIds: {
                remove: true,
                minify: true,
                force: true,
              },
              cleanupNumericValues: {
                floatPrecision: 2,
              },
              convertPathData: {
                floatPrecision: 2,
              },
              convertTransform: {
                floatPrecision: 2,
              },
            },
          },
        },
      ],
};
