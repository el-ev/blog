export default {
  multipass: true,
  plugins:
      [
        {
          name: 'preset-default',
          params: {
            overrides: {
              cleanupIds: false,
              removeHiddenElems: false,
              removeUselessDefs: false,
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
