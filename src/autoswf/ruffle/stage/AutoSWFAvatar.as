package {
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.geom.Point;

    /** Stands in for AQW's AvatarMC: the armor's head registers its game labels here (addAnimationListener) and finds
     *  the skeleton as mcChar (parent.parent.parent of the head is this avatar). Playing a game label follows the
     *  client's mcSkel.gotoAndPlay: only the first listener runs; when its flag is set and the label is not Idle the
     *  skeleton does not play it. */
    public dynamic class AutoSWFAvatar extends MovieClip {
        /** Walking speed, px a frame (spec §5.7b). */
        public static const SPEED:Number = 4;

        public var animEvents:Object = {};
        public var mcChar:AutoSWFSkeleton;
        public var label:String = "";
        public var walking:Boolean = false;
        /** (message:String):void — told when the armor's code throws. */
        public var onError:Function;
        /** (label:String):void — told each time a game label is played (walk arrival included). */
        public var onPlay:Function;
        private var target:Point;
        private var arrived:Function;

        public function AutoSWFAvatar(slots:Array, tracks:Object) {
            super();
            mcChar = new AutoSWFSkeleton(this, slots, tracks);
            addChild(mcChar);
            addEventListener(Event.ENTER_FRAME, onWalk);
        }

        /** Walk to (x, y) in the parent's space like a player clicking the ground: plays Walk, faces where it goes,
         *  plays Idle on arrival, then calls `then`. */
        public function walkTo(x:Number, y:Number, then:Function = null):void {
            target = new Point(x, y);
            arrived = then;
            face(x - this.x);
            if (!walking) {
                walking = true;
                playLabel("Walk");
            }
        }

        /** Face right (dx > 0) or left (dx < 0), as AQW turns the avatar. */
        public function face(dx:Number):void {
            if (dx != 0) mcChar.scaleX = dx < 0 ? -1 : 1;
        }

        private function onWalk(e:Event):void {
            if (!walking || mcChar.paused) return;
            var dx:Number = target.x - x;
            var dy:Number = target.y - y;
            var d:Number = Math.sqrt(dx * dx + dy * dy);
            if (d > SPEED) {
                x += dx / d * SPEED;
                y += dy / d * SPEED;
                return;
            }
            x = target.x;
            y = target.y;
            walking = false;
            playLabel("Idle");
            var then:Function = arrived;
            arrived = null;
            if (then != null) then();
        }

        public function addAnimationListener(label:String, fn:Function, block:Boolean = false):void {
            var list:Array = animEvents[label] as Array;
            if (list == null) {
                list = [];
                animEvents[label] = list;
            }
            for each (var entry:Array in list) {
                if (entry[0] == fn) return;
            }
            list.push([fn, block]);
        }

        public function removeAnimationListener(label:String, fn:Function):void {
            var list:Array = animEvents[label] as Array;
            if (list == null) return;
            for (var i:int = list.length - 1; i >= 0; i--) {
                if (list[i][0] == fn) list.splice(i, 1);
            }
        }

        public function clearAnimEvents():void {
            animEvents = {};
        }

        public function playLabel(label:String):void {
            this.label = label;
            if (onPlay != null) onPlay(label);
            var list:Array = animEvents[label] as Array;
            if (list != null && list.length > 0) {
                try {
                    (list[0][0] as Function)();
                } catch (e:Error) {
                    if (onError != null) onError(e.message);
                }
                if (list[0][1] && label != "Idle") return;
            }
            mcChar.playLabel(label);
        }
    }
}
