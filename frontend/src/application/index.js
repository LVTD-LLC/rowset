import "../styles/index.css";

import { Application } from "@hotwired/stimulus";
import { definitionsFromContext } from "@hotwired/stimulus-webpack-helpers";

import Dropdown from '@stimulus-components/dropdown';
import RevealController from '@stimulus-components/reveal';

const application = Application.start();

const context = import.meta.webpackContext("../controllers", {
  recursive: true,
  regExp: /\.js$/,
});
application.load(definitionsFromContext(context));

application.register('dropdown', Dropdown);
application.register('reveal', RevealController);
