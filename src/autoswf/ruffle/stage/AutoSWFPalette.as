package {
    import flash.display.Sprite;
    import flash.events.MouseEvent;
    import flash.text.TextField;

    /** The six player colors (Hair, Skin, Eye, Base, Trim, Accessory); clicking one opens a grid of colors and the
     *  chosen one applies at once (AutoSWFStage.setPlayerColor). */
    public class AutoSWFPalette extends Sprite {
        public static const LOCATIONS:Array = ["Hair", "Skin", "Eye", "Base", "Trim", "Accessory"];
        private var stageRef:AutoSWFStage;
        private var swatches:Object = {};
        private var grid:Sprite;

        public function AutoSWFPalette(stageRef:AutoSWFStage) {
            super();
            this.stageRef = stageRef;
            var title:TextField = AutoSWFButton.text("PLAYER COLORS", 10, AutoSWFButton.GOLD, true);
            title.x = 8;
            addChild(title);
            for (var i:int = 0; i < LOCATIONS.length; i++) {
                var location:String = LOCATIONS[i];
                var cell:Sprite = new Sprite();
                cell.x = 10 + (i % 3) * 68;
                cell.y = 20 + int(i / 3) * 40;
                var swatch:Sprite = new Sprite();
                cell.addChild(swatch);
                var name:TextField = AutoSWFButton.text(location, 9, AutoSWFButton.CREAM);
                name.y = 22;
                cell.addChild(name);
                cell.buttonMode = true;
                cell.mouseChildren = false;
                cell.addEventListener(MouseEvent.CLICK, opener(location));
                swatches[location] = swatch;
                addChild(cell);
            }
            refresh();
        }

        private function opener(location:String):Function {
            return function (e:MouseEvent):void { open(location); };
        }

        public function refresh():void {
            for each (var location:String in LOCATIONS) {
                var s:Sprite = swatches[location];
                s.graphics.clear();
                s.graphics.lineStyle(1, 0x000000);
                s.graphics.beginFill(uint(stageRef.colors[location]));
                s.graphics.drawRect(0, 0, 22, 20);
                s.graphics.endFill();
            }
        }

        /** A grid of colors for one location, above the swatches. */
        public function open(location:String):void {
            close();
            grid = new Sprite();
            grid.graphics.lineStyle(2, AutoSWFButton.GOLD);
            grid.graphics.beginFill(AutoSWFButton.BROWN);
            grid.graphics.drawRect(0, 0, 212, 132);
            grid.graphics.endFill();
            var title:TextField = AutoSWFButton.text(location, 10, AutoSWFButton.CREAM, true);
            title.x = 6;
            title.y = 2;
            grid.addChild(title);
            var colors:Array = AutoSWFPalette.choices();
            for (var i:int = 0; i < colors.length; i++) {
                var c:Sprite = new Sprite();
                c.x = 6 + (i % 12) * 17;
                c.y = 20 + int(i / 12) * 18;
                c.graphics.lineStyle(1, 0x000000);
                c.graphics.beginFill(colors[i]);
                c.graphics.drawRect(0, 0, 15, 16);
                c.graphics.endFill();
                c.buttonMode = true;
                c.addEventListener(MouseEvent.CLICK, picker(location, colors[i]));
                grid.addChild(c);
            }
            grid.x = 4;
            grid.y = -136;
            addChild(grid);
        }

        private function picker(location:String, rgb:uint):Function {
            return function (e:MouseEvent):void {
                stageRef.setPlayerColor(location, rgb);
                refresh();
                close();
            };
        }

        public function close():void {
            if (grid != null && grid.parent == this) removeChild(grid);
            grid = null;
        }

        /** 12 hues in 5 shades, then grays. */
        public static function choices():Array {
            var out:Array = [];
            var levels:Array = [[0.35, 1], [0.6, 1], [0.9, 0.9], [0.9, 0.55], [0.6, 0.3]];
            for each (var level:Array in levels) {
                for (var h:int = 0; h < 360; h += 30) out.push(hsv(h, level[0], level[1]));
            }
            for (var g:int = 0; g < 12; g++) {
                var v:uint = uint(Math.round(255 * g / 11));
                out.push(v << 16 | v << 8 | v);
            }
            return out;
        }

        private static function hsv(h:Number, s:Number, v:Number):uint {
            var c:Number = v * s;
            var x:Number = c * (1 - Math.abs((h / 60) % 2 - 1));
            var m:Number = v - c;
            var rgb:Array = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c]
                : h < 300 ? [x, 0, c] : [c, 0, x];
            return uint(Math.round((rgb[0] + m) * 255)) << 16 | uint(Math.round((rgb[1] + m) * 255)) << 8 |
                uint(Math.round((rgb[2] + m) * 255));
        }
    }
}
