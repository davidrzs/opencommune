import { normalize } from './types';

// Other names of communes, in the other national languages (and English where it has its own), so
// the finder knows "Genf" and "Sitten". BFS number -> names besides the official one.
export const otherNames: Record<number, string[]> = {
  6621: ['Genf', 'Ginevra', 'Geneva'],
  6266: ['Sitten'],
  2196: ['Freiburg', 'Friburgo'],
  6458: ['Neuenburg'],
  371: ['Bienna'],
  351: ['Berne', 'Berna'],
  2701: ['Bâle', 'Basilea'],
  261: ['Zurich', 'Zurigo'],
  1061: ['Lucerne', 'Lucerna'],
  3203: ['Sankt Gallen', 'Saint-Gall', 'San Gallo'],
  5586: ['Losanna'],
  3901: ['Coire', 'Coira'],
  2601: ['Soleure', 'Soletta'],
  2939: ['Schaffhouse', 'Sciaffusa'],
  1632: ['Glaris', 'Glarona'],
  1372: ['Schwytz', 'Svitto'],
  1711: ['Zoug', 'Zugo'],
  6711: ['Delsberg'],
  6800: ['Pruntrut'],
  6831: ['Münster'],
  723: ['Neuenstadt'],
  6136: ['Martinach'],
  6248: ['Siders'],
  6297: ['Viège'],
  6110: ['Loèche'],
  6113: ['Salquenen'],
  6002: ['Brigue-Glis'],
  2275: ['Morat'],
  2054: ['Stäffis am See'],
  2135: ['Greyerz'],
  2096: ['Remund'],
  5002: ['Bellenz'],
  942: ['Thoune'],
  5890: ['Vivis'],
  5938: ['Iferten'],
  5822: ['Peterlingen'],
  5451: ['Wiflisburg']
};

// The form names are compared in: no accents or case, ae/oe/ue as a/o/u ("Zuerich"), punctuation
// as spaces ("St. Gallen", "St Gallen").
export const searchKey = (name: string) =>
  normalize(name)
    .replace(/ae/g, 'a')
    .replace(/oe/g, 'o')
    .replace(/ue/g, 'u')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
