package {
    import flash.display.MovieClip;
    import flash.display.Sprite;
    import flash.events.Event;
    import flash.geom.ColorTransform;

    /** The target to aim skills at: AQW's own Training Dummy when AutoSWF embedded it (wear), else a post and a straw
     *  target drawn by AutoSWF. Clicking selects it (a ring under it, like AQW's target ring); hit() plays the
     *  monster's Hit, or flashes and wobbles the drawn one. */
    public class AutoSWFDummy extends Sprite {
        public var hits:int = 0;
        /** AQW's Training Dummy clip, once worn. */
        public var monster:MovieClip;
        private var ring:Sprite = new Sprite();
        private var body:Sprite = new Sprite();
        private var wobble:int = 0;
        private var picked:Boolean = false;

        public function AutoSWFDummy() {
            super();
            ring.graphics.lineStyle(3, 0xFFD24A);
            ring.graphics.drawEllipse(-42, -10, 84, 20);
            ring.visible = false;
            addChild(ring);
            var g:* = body.graphics;
            g.beginFill(0x6B4A2B);
            g.drawRect(-5, -118, 10, 118);
            g.endFill();
            g.beginFill(0x5A3D22);
            g.drawRect(-26, -8, 52, 8);
            g.endFill();
            g.beginFill(0xD8B75A);
            g.drawRect(-28, -96, 56, 10);
            g.endFill();
            for each (var ring2:Array in [[30, 0xE8D49A], [22, 0xB04A3B], [14, 0xE8D49A], [6, 0xB04A3B]]) {
                g.beginFill(ring2[1]);
                g.drawCircle(0, -128, ring2[0]);
                g.endFill();
            }
            addChild(body);
            buttonMode = true;
            addEventListener(Event.ENTER_FRAME, onFrame);
        }

        public function get selected():Boolean {
            return picked;
        }

        public function set selected(value:Boolean):void {
            picked = value;
            ring.visible = value;
        }

        /** Show AQW's Training Dummy instead of the drawn one. */
        public function wear(clip:MovieClip):void {
            monster = clip;
            body.visible = false;
            addChild(monster);
        }

        public function hit():void {
            hits++;
            if (monster != null) monster.gotoAndPlay("Hit");
            else wobble = 12;
        }

        private function onFrame(e:Event):void {
            if (wobble <= 0) return;
            wobble--;
            body.rotation = wobble == 0 ? 0 : (wobble % 2 == 0 ? 6 : -6) * wobble / 12;
            body.transform.colorTransform = wobble > 8 ? new ColorTransform(1, 1, 1, 1, 120, 120, 120, 0)
                : new ColorTransform();
        }
    }
}
